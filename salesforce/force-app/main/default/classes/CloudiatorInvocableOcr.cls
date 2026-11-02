/** Flow invocable: Cloudiator: OCR. Pass JSON body matching the OpenAPI operation. */
public with sharing class CloudiatorInvocableOcr {
    public class Request {
        @InvocableVariable(required=true label='JSON body') public String jsonBody;
        @InvocableVariable(label='Related Record Id') public String relatedRecordId;
    }
    public class Response {
        @InvocableVariable(label='OK') public Boolean ok;
        @InvocableVariable(label='Text / summary') public String text;
        @InvocableVariable(label='Artifact Id') public String artifactId;
        @InvocableVariable(label='Request Id') public String requestId;
        @InvocableVariable(label='HTTP status') public Integer statusCode;
        @InvocableVariable(label='Error') public String errorMessage;
        @InvocableVariable(label='Call Log Id') public Id logId;
        @InvocableVariable(label='Raw body') public String body;
    }
    @InvocableMethod(label='Cloudiator: OCR' category='Cloudiator')
    public static List<Response> run(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Map<String, Object> payload = String.isBlank(req.jsonBody)
                ? new Map<String, Object>()
                : (Map<String, Object>) JSON.deserializeUntyped(req.jsonBody);
            CloudiatorService.Result r = CloudiatorService.tool('OCR', '/v1/tools/ocr', payload, 'Image', 'Text', req.relatedRecordId);
            Response resp = new Response();
            resp.ok = r.ok; resp.text = r.text; resp.artifactId = r.artifactId;
            resp.requestId = r.requestId; resp.statusCode = r.statusCode;
            resp.errorMessage = r.errorMessage; resp.logId = r.logId; resp.body = r.body;
            if (String.isBlank(resp.text)) resp.text = r.body;
            out.add(resp);
        }
        return out;
    }
}
