/**
 * The invocable the Flow calls. It hands each request to a retrying Queueable,
 * CanvasSyncJob, which does the query, the signing, the callout, the retry
 * classification, and the status writeback. Keeping this thin invocable means
 * the Flow does not change when the delivery mechanism does.
 */
public with sharing class CanvasSyncEmitter {

    public class Request {
        @InvocableVariable(required=true) public Id contactId;
        @InvocableVariable(required=true) public String intent; // sync or delete
    }

    @InvocableMethod(label='Emit Canvas Sync')
    public static void emit(List<Request> requests) {
        for (Request r : requests) {
            System.enqueueJob(new CanvasSyncJob(r.contactId, r.intent));
        }
    }
}
