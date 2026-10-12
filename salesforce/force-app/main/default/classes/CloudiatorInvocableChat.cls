/** Flow / Apex invocable: chat completions. */
public with sharing class CloudiatorInvocableChat {
    public class Request {
        @InvocableVariable(required=true label='Prompt') public String prompt;
        @InvocableVariable(label='Model') public String model;
        @InvocableVariable(label='Max tokens') public Integer maxTokens;
        @InvocableVariable(label='Related Record Id') public String relatedRecordId;
    }
    public class Response {
        @InvocableVariable(label='OK') public Boolean ok;
        @InvocableVariable(label='Assistant text') public String text;
        @InvocableVariable(label='Request Id') public String requestId;
        @InvocableVariable(label='HTTP status') public Integer statusCode;
        @InvocableVariable(label='Error') public String errorMessage;
        @InvocableVariable(label='Call Log Id') public Id logId;
        @InvocableVariable(label='Raw body') public String body;
    }
    @InvocableMethod(label='Cloudiator: Chat' description='POST /v1/chat/completions (stream=false)' category='Cloudiator')
    public static List<Response> run(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            CloudiatorService.Result r = CloudiatorService.chat(req.prompt, req.model, req.maxTokens, req.relatedRecordId);
            Response resp = new Response();
            resp.ok = r.ok; resp.text = r.text; resp.requestId = r.requestId;
            resp.statusCode = r.statusCode; resp.errorMessage = r.errorMessage;
            resp.logId = r.logId; resp.body = r.body;
            out.add(resp);
        }
        return out;
    }
}
