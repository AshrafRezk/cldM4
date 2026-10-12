/** Flow invocable: embeddings. */
public with sharing class CloudiatorInvocableEmbeddings {
    public class Request {
        @InvocableVariable(required=true label='Input text') public String inputText;
        @InvocableVariable(label='Related Record Id') public String relatedRecordId;
    }
    public class Response {
        @InvocableVariable(label='OK') public Boolean ok;
        @InvocableVariable(label='Request Id') public String requestId;
        @InvocableVariable(label='HTTP status') public Integer statusCode;
        @InvocableVariable(label='Error') public String errorMessage;
        @InvocableVariable(label='Call Log Id') public Id logId;
        @InvocableVariable(label='Raw body') public String body;
    }
    @InvocableMethod(label='Cloudiator: Embeddings' category='Cloudiator')
    public static List<Response> run(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            CloudiatorService.Result r = CloudiatorService.embeddings(req.inputText, req.relatedRecordId);
            Response resp = new Response();
            resp.ok = r.ok; resp.requestId = r.requestId; resp.statusCode = r.statusCode;
            resp.errorMessage = r.errorMessage; resp.logId = r.logId; resp.body = r.body;
            out.add(resp);
        }
        return out;
    }
}
