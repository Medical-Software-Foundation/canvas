@isTest
private class CanvasSyncEmitterTest {

    // A mock that captures the request and answers with a configurable status.
    private class MockCallout implements HttpCalloutMock {
        public HttpRequest captured;
        private Integer status;
        private String body;
        public MockCallout(Integer status, String body) {
            this.status = status;
            this.body = body;
        }
        public HttpResponse respond(HttpRequest req) {
            this.captured = req;
            HttpResponse res = new HttpResponse();
            res.setStatusCode(status);
            res.setBody(body);
            return res;
        }
    }

    // The config the job reads, injected through the test seam since custom
    // metadata cannot be inserted by DML.
    private static Webhook_Config__mdt testConfig() {
        return new Webhook_Config__mdt(
            Secret__c = 'shhh',
            Endpoint__c = 'https://example.canvasmedical.com/webhook',
            Fields__c = 'FirstName,LastName,Birthdate,Email,Phone'
        );
    }

    @isTest
    static void emitEnqueuesAndDeliversSyncWithFullRecord() {
        Contact c = new Contact(
            FirstName = 'Ada', LastName = 'Lovelace',
            Birthdate = Date.newInstance(1815, 12, 10),
            Email = 'ada@example.com', Phone = '555-0100'
        );
        insert c;

        MockCallout mock = new MockCallout(202, '{"status":"accepted"}');
        Test.setMock(HttpCalloutMock.class, mock);
        CanvasSyncJob.configOverride = testConfig();

        CanvasSyncEmitter.Request r = new CanvasSyncEmitter.Request();
        r.contactId = c.Id;
        r.intent = 'sync';

        Test.startTest();
        CanvasSyncEmitter.emit(new List<CanvasSyncEmitter.Request>{ r });
        Test.stopTest(); // the enqueued job runs here

        System.assertNotEquals(null, mock.captured, 'the job should have fired the callout');
        Map<String, Object> sent = (Map<String, Object>) JSON.deserializeUntyped(mock.captured.getBody());
        System.assertEquals('sync', sent.get('intent'));
        Map<String, Object> rec = (Map<String, Object>) sent.get('record');
        System.assertEquals(c.Id, (Id) rec.get('Id'));
        System.assertEquals('Ada', rec.get('FirstName'));
        System.assert(mock.captured.getHeader('X-Signature').startsWith('sha256='), 'signature header present');

        Contact after = [SELECT Canvas_Sync_Status__c FROM Contact WHERE Id = :c.Id];
        System.assertEquals('Delivered', after.Canvas_Sync_Status__c);
    }

    @isTest
    static void deliveredDeleteCarriesIdOnly() {
        Contact c = new Contact(FirstName = 'Grace', LastName = 'Hopper');
        insert c;

        MockCallout mock = new MockCallout(202, '{"status":"accepted"}');
        Test.setMock(HttpCalloutMock.class, mock);
        CanvasSyncJob.configOverride = testConfig();

        CanvasSyncEmitter.Request r = new CanvasSyncEmitter.Request();
        r.contactId = c.Id;
        r.intent = 'delete';

        Test.startTest();
        CanvasSyncEmitter.emit(new List<CanvasSyncEmitter.Request>{ r });
        Test.stopTest();

        Map<String, Object> sent = (Map<String, Object>) JSON.deserializeUntyped(mock.captured.getBody());
        System.assertEquals('delete', sent.get('intent'));
        Map<String, Object> rec = (Map<String, Object>) sent.get('record');
        System.assertEquals(c.Id, (Id) rec.get('Id'));
        System.assertEquals(false, rec.containsKey('FirstName'), 'delete carries Id only');
    }
}
