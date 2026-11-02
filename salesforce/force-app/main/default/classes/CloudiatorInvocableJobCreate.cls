/** Flow invocable: create image generation job (needs image_generation scope). */
public with sharing class CloudiatorInvocableJobCreate {
    public class Request {
        @InvocableVariable(required=true label='Prompt') public String prompt;
        @InvocableVariable(label='Idempotency Key') public String idempotencyKey;
        @InvocableVariable(label='Related Record Id') public String relatedRecordId;
    }
    public class Response {
        @InvocableVariable(label='OK') public Boolean ok;
        @InvocableVariable(label='Job Id') public String text;
        @InvocableVariable(label='Request Id') public String requestId;
        @InvocableVariable(label='HTTP status') public Integer statusCode;
        @InvocableVariable(label='Error') public String errorMessage;
        @InvocableVariable(label='Call Log Id') public Id logId;
        @InvocableVariable(label='Raw body') public String body;
    }
    @InvocableMethod(label='Cloudiator: Create image job' category='Cloudiator')
    public static List<Response> run(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Map<String, Object> payload = new Map<String, Object>{
                'kind' => 'image',
                'prompt' => req.prompt
            };
            CloudiatorService.Result r = CloudiatorService.createJob(payload, req.idempotencyKey, req.relatedRecordId);
            Response resp = new Response();
            resp.ok = r.ok; resp.text = r.text; resp.requestId = r.requestId;
            resp.statusCode = r.statusCode; resp.errorMessage = r.errorMessage;
            resp.logId = r.logId; resp.body = r.body;
            out.add(resp);
        }
        return out;
    }
}
