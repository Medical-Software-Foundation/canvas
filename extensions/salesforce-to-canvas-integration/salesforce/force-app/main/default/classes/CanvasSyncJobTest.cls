@isTest
private class CanvasSyncJobTest {

    private class MockCallout implements HttpCalloutMock {
        private Integer status;
        private String body;
        public MockCallout(Integer status, String body) {
            this.status = status;
            this.body = body;
        }
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(status);
            res.setBody(body);
            return res;
        }
    }

    private static Webhook_Config__mdt fullConfig() {
        return new Webhook_Config__mdt(
            Secret__c = 'shhh',
            Endpoint__c = 'https://example.canvasmedical.com/webhook',
            Fields__c = 'FirstName,LastName,Birthdate,Email,Phone'
        );
    }

    private static Id syncOnce(Integer status, String body, Webhook_Config__mdt cfg) {
        Contact c = new Contact(FirstName = 'Test', LastName = 'Person');
        insert c;
        Test.setMock(HttpCalloutMock.class, new MockCallout(status, body));
        CanvasSyncJob.configOverride = cfg;
        Test.startTest();
        System.enqueueJob(new CanvasSyncJob(c.Id, 'sync'));
        Test.stopTest();
        return c.Id;
    }

    @isTest
    static void permanentRejectionFailsWithoutRetry() {
        Id cid = syncOnce(400, '{"error":"bad request"}', fullConfig());
        Contact after = [SELECT Canvas_Sync_Status__c, Canvas_Sync_Last_Error__c FROM Contact WHERE Id = :cid];
        System.assertEquals('Failed', after.Canvas_Sync_Status__c);
        System.assert(after.Canvas_Sync_Last_Error__c.contains('400'), 'error names the status');
    }

    @isTest
    static void transientFailureRecordsRetrying() {
        Id cid = syncOnce(503, '{"error":"unavailable"}', fullConfig());
        // In a test context the chain is not enqueued, the Retrying status the
        // job writes before the enqueue is the assertion. See journal cnv-941/036.
        Contact after = [SELECT Canvas_Sync_Status__c FROM Contact WHERE Id = :cid];
        System.assertEquals('Retrying', after.Canvas_Sync_Status__c);
    }

    @isTest
    static void missingConfigFailsWithoutCallout() {
        // A blank secret degrades visibly rather than throwing the old query
        // exception, and it does not retry since it will not self heal.
        Id cid = syncOnce(202, '{}', new Webhook_Config__mdt(
            Secret__c = '', Endpoint__c = 'https://example.canvasmedical.com/webhook', Fields__c = 'LastName'
        ));
        Contact after = [SELECT Canvas_Sync_Status__c, Canvas_Sync_Last_Error__c FROM Contact WHERE Id = :cid];
        System.assertEquals('Failed', after.Canvas_Sync_Status__c);
        System.assert(after.Canvas_Sync_Last_Error__c.contains('secret'), 'error names the missing config');
    }

    @isTest
    static void unknownFieldIsSkippedNotFatal() {
        Contact c = new Contact(FirstName = 'Ada', LastName = 'Lovelace');
        insert c;
        Test.setMock(HttpCalloutMock.class, new MockCallout(202, '{}'));
        CanvasSyncJob.configOverride = new Webhook_Config__mdt(
            Secret__c = 'shhh',
            Endpoint__c = 'https://example.canvasmedical.com/webhook',
            Fields__c = 'FirstName,LastName,NotARealField__c'
        );
        Test.startTest();
        System.enqueueJob(new CanvasSyncJob(c.Id, 'sync'));
        Test.stopTest();
        Contact after = [SELECT Canvas_Sync_Status__c FROM Contact WHERE Id = :c.Id];
        System.assertEquals('Delivered', after.Canvas_Sync_Status__c, 'a bad field name does not break the sync');
    }
}
