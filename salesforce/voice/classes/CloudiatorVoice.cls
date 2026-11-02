/**
 * Shared callout helper for the Cloudiator voice API.
 * Named Credential "Cloudiator" carries the sk-cld- key; never hardcode it.
 */
public with sharing class CloudiatorVoice {
    public static final String NAMED_CREDENTIAL = 'callout:Cloudiator';

    public class CalloutFailure extends Exception {}

    public static Object send(String method, String path, Object body) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint(NAMED_CREDENTIAL + path);
        req.setMethod(method);
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(120000);
        if (body != null) {
            req.setBody(JSON.serialize(body));
        }
        HttpResponse res = new Http().send(req);
        String requestId = res.getHeader('X-Request-Id');
        if (res.getStatusCode() >= 300) {
            throw new CalloutFailure(
                method + ' ' + path + ' -> ' + res.getStatusCode() + ' ' + errorMessage(res.getBody())
                + ' (X-Request-Id ' + requestId + ')'
            );
        }
        return JSON.deserializeUntyped(res.getBody());
    }

    /** Binary body (a recording). Same Named Credential, timeout and errors. */
    public static Object sendBlob(String method, String path, Blob body, String contentType) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint(NAMED_CREDENTIAL + path);
        req.setMethod(method);
        req.setHeader('Content-Type', contentType);
        req.setTimeout(120000);
        req.setBodyAsBlob(body);
        HttpResponse res = new Http().send(req);
        if (res.getStatusCode() >= 300) {
            throw new CalloutFailure(
                method + ' ' + path + ' -> ' + res.getStatusCode() + ' ' + errorMessage(res.getBody())
                + ' (X-Request-Id ' + res.getHeader('X-Request-Id') + ')'
            );
        }
        return JSON.deserializeUntyped(res.getBody());
    }

    private static String errorMessage(String body) {
        try {
            Map<String, Object> parsed = (Map<String, Object>) JSON.deserializeUntyped(body);
            Map<String, Object> error = (Map<String, Object>) parsed.get('error');
            return String.valueOf(error.get('message'));
        } catch (Exception e) {
            // An HTML page here means Cloudflare challenged Apex (docs/salesforce.md).
            return body == null ? '' : body.left(200);
        }
    }
}
