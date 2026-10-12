/** Flow invocable: poll one job (one callout per interview/transaction). */
public with sharing class CloudiatorInvocableJobPoll {
    public class Request {
        @InvocableVariable(required=true label='Job Id') public String jobId;
        @InvocableVariable(label='Related Record Id') public String relatedRecordId;
    }
    public class Response {
        @InvocableVariable(label='OK') public Boolean ok;
        @InvocableVariable(label='Status / text') public String text;
        @InvocableVariable(label='Artifact Id') public String artifactId;
        @InvocableVariable(label='Request Id') public String requestId;
        @InvocableVariable(label='HTTP status') public Integer statusCode;
        @InvocableVariable(label='Error') public String errorMessage;
        @InvocableVariable(label='Call Log Id') public Id logId;
        @InvocableVariable(label='Raw body') public String body;
    }
    @InvocableMethod(label='Cloudiator: Poll job' category='Cloudiator')
    public static List<Response> run(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            CloudiatorService.Result r = CloudiatorService.getJob(req.jobId, req.relatedRecordId);
            Response resp = new Response();
            resp.ok = r.ok; resp.text = r.text; resp.artifactId = r.artifactId;
            resp.requestId = r.requestId; resp.statusCode = r.statusCode;
            resp.errorMessage = r.errorMessage; resp.logId = r.logId; resp.body = r.body;
            if (r.ok && r.body != null) {
                try {
                    Map<String, Object> m = (Map<String, Object>) JSON.deserializeUntyped(r.body);
                    resp.text = String.valueOf(m.get('status'));
                } catch (Exception ignore) {}
            }
            out.add(resp);
        }
        return out;
    }
}
