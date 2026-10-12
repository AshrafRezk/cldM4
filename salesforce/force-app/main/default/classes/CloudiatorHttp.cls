/**
 * Low-level HTTP to Cloudiator. Prefer Named Credential callout:Cloudiator when
 * Use_Named_Credential__c is true; otherwise Bearer from protected config + Remote Site.
 */
public with sharing class CloudiatorHttp {
    public class Response {
        public Integer statusCode;
        public String body;
        public String requestId;
        public Long durationMs;
        public Map<String, Object> json;
    }

    public static Response request(String method, String path, Object body, Integer timeoutMs) {
        CloudiatorConfig.Settings cfg = CloudiatorConfig.get();
        Long started = System.now().getTime();
        HttpRequest req = new HttpRequest();
        String relative = path.startsWith('/') ? path : '/' + path;
        if (cfg.useNamedCredential == true) {
            req.setEndpoint('callout:Cloudiator' + relative);
        } else {
            if (String.isBlank(cfg.apiKey)) {
                throw new CalloutException('Cloudiator API key not configured. Open the Cloudiator Setup tab.');
            }
            req.setEndpoint(cfg.baseUrl + relative);
            req.setHeader('Authorization', 'Bearer ' + cfg.apiKey);
        }
        req.setMethod(method);
        req.setTimeout(timeoutMs == null ? 120000 : timeoutMs);
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('Accept', 'application/json');
        if (body != null && method != 'GET' && method != 'HEAD') {
            req.setBody(JSON.serialize(body));
        }
        HttpResponse res = new Http().send(req);
        Response out = new Response();
        out.statusCode = res.getStatusCode();
        out.body = res.getBody();
        out.requestId = res.getHeader('X-Request-Id');
        out.durationMs = System.now().getTime() - started;
        if (String.isNotBlank(out.body) && out.body.trim().startsWith('{')) {
            try {
                out.json = (Map<String, Object>) JSON.deserializeUntyped(out.body);
            } catch (Exception ignore) {
                out.json = null;
            }
        }
        return out;
    }
}
