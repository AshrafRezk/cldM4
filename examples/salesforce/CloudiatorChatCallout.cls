/**
 * Sync chat against Named Credential "Cloudiator".
 * Requires External Credential principal permission set on the running user.
 * Docs: docs/salesforce.md
 */
public class CloudiatorChatCallout {
    public class Result {
        public Integer statusCode;
        public String requestId;
        public String body;
        public String assistantText;
    }

    public static Result chat(String prompt) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:Cloudiator/v1/chat/completions');
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(120000);
        req.setBody(JSON.serialize(new Map<String, Object>{
            'model' => 'gemma4:e4b-it-qat',
            'stream' => false,
            'max_tokens' => 512,
            'messages' => new List<Object>{
                new Map<String, Object>{ 'role' => 'user', 'content' => prompt }
            }
        }));

        HttpResponse res = new Http().send(req);
        Result out = new Result();
        out.statusCode = res.getStatusCode();
        out.requestId = res.getHeader('X-Request-Id');
        out.body = res.getBody();

        if (out.statusCode >= 200 && out.statusCode < 300 && String.isNotBlank(out.body)) {
            Map<String, Object> root = (Map<String, Object>) JSON.deserializeUntyped(out.body);
            List<Object> choices = (List<Object>) root.get('choices');
            if (choices != null && !choices.isEmpty()) {
                Map<String, Object> choice0 = (Map<String, Object>) choices[0];
                Map<String, Object> message = (Map<String, Object>) choice0.get('message');
                if (message != null) {
                    out.assistantText = (String) message.get('content');
                }
            }
        }
        return out;
    }
}
