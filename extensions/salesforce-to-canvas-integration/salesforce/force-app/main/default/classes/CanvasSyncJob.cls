/**
 * The deliberate Canvas sync, delivered by a retrying Queueable.
 *
 * The Flow calls CanvasSyncEmitter, which enqueues one of these per Contact.
 * The job queries the Contact, builds the signed payload, posts it to the
 * Canvas plugin webhook, reads the response, and writes the outcome back onto
 * the Contact so a rep sees a failure on the record they are already looking at.
 *
 * Reliability lives here, not in a Canvas side poller, because the integration
 * is events only. A 202 is delivered. A 400 or 401 is permanent and never
 * retries, a bad body or a bad secret will not succeed on a delay. A 5xx, a
 * timeout, or a thrown CalloutException is transient and re enqueues with a
 * growing delay up to a cap. A Finalizer records a Failed status even when an
 * unhandled limit exception escapes the try blocks. See journal cnv-941/036.
 */
public with sharing class CanvasSyncJob implements Queueable, Database.AllowsCallouts {

    // Salesforce caps an enqueue delay at ten minutes, so the backoff saturates
    // there. Five attempts spans a few minutes of transient outage before the
    // job gives up and leaves a Failed status for the rep.
    private static final Integer MAX_ATTEMPTS = 5;

    // A test seam. Custom metadata cannot be inserted by DML in a test, so a
    // test sets this to drive the config rather than relying on the org record.
    @TestVisible
    private static Webhook_Config__mdt configOverride;

    private final Id contactId;
    private final String intent;
    private final Integer attempt;

    public CanvasSyncJob(Id contactId, String intent) {
        this(contactId, intent, 0);
    }

    public CanvasSyncJob(Id contactId, String intent, Integer attempt) {
        this.contactId = contactId;
        this.intent = intent;
        this.attempt = attempt;
    }

    public void execute(QueueableContext ctx) {
        // The Finalizer catches an unhandled limit exception that the try blocks
        // below cannot, so a hard failure still records a status.
        System.attachFinalizer(new StatusFinalizer(contactId, attempt));

        Webhook_Config__mdt cfg = readConfig();
        if (cfg == null || String.isBlank(cfg.Secret__c) || String.isBlank(cfg.Endpoint__c)) {
            // A misconfiguration will not fix itself on a delay, so do not retry.
            writeStatus('Failed', 'Webhook Config Default record is missing the endpoint or the secret');
            return;
        }

        String body;
        try {
            body = buildBody(cfg);
        } catch (Exception e) {
            writeStatus('Failed', 'Could not build the payload, ' + e.getMessage());
            return;
        }

        HttpRequest req = new HttpRequest();
        req.setEndpoint(cfg.Endpoint__c);
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('X-Signature', sign(body, cfg.Secret__c));
        req.setBody(body);

        try {
            HttpResponse res = new Http().send(req);
            classify(res.getStatusCode(), res.getBody());
        } catch (System.CalloutException e) {
            retryOrFail('Callout failed, ' + e.getMessage());
        }
    }

    private void classify(Integer status, String responseBody) {
        if (status == 202) {
            writeStatus('Delivered', null);
        } else if (status == 400 || status == 401) {
            writeStatus('Failed', 'Canvas rejected the request, HTTP ' + status + ' ' + truncate(responseBody));
        } else {
            retryOrFail('Canvas returned HTTP ' + status + ' ' + truncate(responseBody));
        }
    }

    private void retryOrFail(String message) {
        Integer nextAttempt = attempt + 1;
        if (nextAttempt < MAX_ATTEMPTS) {
            writeStatus('Retrying', message + ' (attempt ' + nextAttempt + ')');
            // A test context allows only one chained enqueue, so the chain is
            // not exercised under test. The Retrying status above is asserted
            // instead. See journal cnv-941/036.
            if (!Test.isRunningTest()) {
                System.enqueueJob(new CanvasSyncJob(contactId, intent, nextAttempt), backoffMinutes(nextAttempt));
            }
        } else {
            writeStatus('Failed', message + ' (gave up after ' + nextAttempt + ' attempts)');
        }
    }

    private Webhook_Config__mdt readConfig() {
        if (configOverride != null) {
            return configOverride;
        }
        List<Webhook_Config__mdt> rows = [
            SELECT Secret__c, Endpoint__c, Fields__c
            FROM Webhook_Config__mdt
            WHERE DeveloperName = 'Default'
            LIMIT 1
        ];
        return rows.isEmpty() ? null : rows[0];
    }

    private String buildBody(Webhook_Config__mdt cfg) {
        List<String> selected = validatedFields(cfg.Fields__c);

        String soql = 'SELECT ' + String.join(selected, ', ') + ' FROM Contact WHERE Id = :contactId LIMIT 1';
        Contact c = Database.query(soql);

        Map<String, Object> record = new Map<String, Object>{ 'Id' => c.Id };
        if (intent == 'sync') {
            for (String f : selected) {
                if (f == 'Id') {
                    continue;
                }
                Object value = c.get(f);
                if (value instanceof Date) {
                    record.put(f, String.valueOf((Date) value));
                } else {
                    record.put(f, value);
                }
            }
        }

        return JSON.serialize(new Map<String, Object>{
            'intent' => intent,
            'record' => record
        });
    }

    // Build the field list from the metadata, always include Id, and validate
    // each configured name against the Contact describe so a typo skips one
    // field rather than breaking the whole query.
    private List<String> validatedFields(String configured) {
        Map<String, Schema.SObjectField> describe = Schema.SObjectType.Contact.fields.getMap();
        List<String> result = new List<String>{ 'Id' };
        if (String.isBlank(configured)) {
            return result;
        }
        for (String raw : configured.split(',')) {
            String name = raw.trim();
            if (String.isBlank(name) || name == 'Id') {
                continue;
            }
            if (describe.containsKey(name.toLowerCase())) {
                result.add(name);
            }
        }
        return result;
    }

    private String sign(String body, String secret) {
        Blob mac = Crypto.generateMac('hmacSHA256', Blob.valueOf(body), Blob.valueOf(secret));
        return 'sha256=' + EncodingUtil.convertToHex(mac);
    }

    // Linear minute backoff capped at the platform ten minute enqueue ceiling.
    private Integer backoffMinutes(Integer nextAttempt) {
        Integer minutes = nextAttempt * 2;
        return minutes > 10 ? 10 : minutes;
    }

    private static String truncate(String value) {
        if (value == null) {
            return '';
        }
        return value.length() > 1000 ? value.substring(0, 1000) : value;
    }

    private void writeStatus(String status, String error) {
        writeStatus(contactId, status, error);
    }

    private static void writeStatus(Id contactId, String status, String error) {
        update new Contact(
            Id = contactId,
            Canvas_Sync_Status__c = status,
            Canvas_Sync_Last_Error__c = error,
            Canvas_Sync_Last_Attempt__c = System.now()
        );
    }

    // Records a Failed status when the job died on an unhandled exception that
    // the execute try blocks could not catch, a governor limit for example.
    public class StatusFinalizer implements Finalizer {
        private final Id contactId;
        private final Integer attempt;

        public StatusFinalizer(Id contactId, Integer attempt) {
            this.contactId = contactId;
            this.attempt = attempt;
        }

        public void execute(FinalizerContext fc) {
            if (fc.getResult() == ParentJobResult.UNHANDLED_EXCEPTION) {
                Exception e = fc.getException();
                String message = e == null ? 'Unhandled exception' : e.getMessage();
                CanvasSyncJob.writeStatus(contactId, 'Failed', 'Job failed unhandled, ' + message);
            }
        }
    }
}
