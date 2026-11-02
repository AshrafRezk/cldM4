/**
 * High-level Cloudiator operations for Apex and Invocable wrappers.
 * Text / image tools are sync. Image generation uses jobs when scoped.
 * Audio transcription is not in the v1 Salesforce engineer preset yet.
 */
public with sharing class CloudiatorService {
    public class Result {
        @AuraEnabled public Boolean ok;
        @AuraEnabled public Integer statusCode;
        @AuraEnabled public String requestId;
        @AuraEnabled public String text;
        @AuraEnabled public String body;
        @AuraEnabled public String artifactId;
        @AuraEnabled public String errorMessage;
        @AuraEnabled public Id logId;
        @AuraEnabled public Long durationMs;
    }

    public static Result chat(String prompt, String model, Integer maxTokens, String relatedRecordId) {
        CloudiatorConfig.Settings cfg = CloudiatorConfig.get();
        Map<String, Object> payload = new Map<String, Object>{
            'model' => String.isBlank(model) ? cfg.defaultModel : model,
            'stream' => false,
            'max_tokens' => maxTokens == null ? 512 : maxTokens,
            'messages' => new List<Object>{
                new Map<String, Object>{ 'role' => 'user', 'content' => prompt }
            }
        };
        return postJson(
            'Chat',
            '/v1/chat/completions',
            payload,
            'Text',
            'Text',
            prompt,
            relatedRecordId,
            true
        );
    }

    public static Result embeddings(String inputText, String relatedRecordId) {
        Map<String, Object> payload = new Map<String, Object>{
            'model' => 'nomic-embed-text',
            'input' => inputText
        };
        return postJson('Embeddings', '/v1/embeddings', payload, 'Text', 'Binary', inputText, relatedRecordId, false);
    }

    public static Result tool(
        String serviceName,
        String path,
        Map<String, Object> payload,
        String modalityIn,
        String modalityOut,
        String relatedRecordId
    ) {
        return postJson(
            serviceName,
            path,
            payload,
            modalityIn,
            modalityOut,
            JSON.serialize(payload),
            relatedRecordId,
            true
        );
    }

    public static Result createJob(Map<String, Object> payload, String idempotencyKey, String relatedRecordId) {
        // Jobs require image_generation (or heavy) scope — not on default engineer key.
        CloudiatorConfig.Settings cfg = CloudiatorConfig.get();
        Long started = System.now().getTime();
        Result r = new Result();
        try {
            HttpRequest req = new HttpRequest();
            if (cfg.useNamedCredential == true) {
                req.setEndpoint('callout:Cloudiator/v1/jobs');
            } else {
                req.setEndpoint(cfg.baseUrl + '/v1/jobs');
                req.setHeader('Authorization', 'Bearer ' + cfg.apiKey);
            }
            req.setMethod('POST');
            req.setTimeout(120000);
            req.setHeader('Content-Type', 'application/json');
            if (String.isNotBlank(idempotencyKey)) {
                req.setHeader('Idempotency-Key', idempotencyKey);
            }
            req.setBody(JSON.serialize(payload));
            HttpResponse res = new Http().send(req);
            CloudiatorHttp.Response wrap = new CloudiatorHttp.Response();
            wrap.statusCode = res.getStatusCode();
            wrap.body = res.getBody();
            wrap.requestId = res.getHeader('X-Request-Id');
            wrap.durationMs = System.now().getTime() - started;
            r = fromHttp('JobCreate', wrap, 'Text', 'Text', JSON.serialize(payload), relatedRecordId, false);
        } catch (Exception e) {
            r.ok = false;
            r.errorMessage = e.getMessage();
            r.logId = CloudiatorLogger.log(
                'JobCreate', false, null, 'Text', 'None', JSON.serialize(payload), null, e.getMessage(), null, relatedRecordId
            );
        }
        return r;
    }

    public static Result getJob(String jobId, String relatedRecordId) {
        CloudiatorHttp.Response res = CloudiatorHttp.request('GET', '/v1/jobs/' + jobId, null, 120000);
        return fromHttp('JobPoll', res, 'None', 'Mixed', jobId, relatedRecordId, true);
    }

    public static Result health() {
        CloudiatorHttp.Response res = CloudiatorHttp.request('GET', '/v1/health', null, 15000);
        return fromHttp('Health', res, 'None', 'Text', null, null, false);
    }

    private static Result postJson(
        String service,
        String path,
        Object payload,
        String modalityIn,
        String modalityOut,
        String inputSummary,
        String relatedRecordId,
        Boolean extractAssistant
    ) {
        Result r = new Result();
        try {
            CloudiatorHttp.Response res = CloudiatorHttp.request('POST', path, payload, 120000);
            r = fromHttp(service, res, modalityIn, modalityOut, inputSummary, relatedRecordId, extractAssistant);
        } catch (Exception e) {
            r.ok = false;
            r.errorMessage = e.getMessage();
            r.logId = CloudiatorLogger.log(
                service, false, null, modalityIn, modalityOut, inputSummary, null, e.getMessage(), null, relatedRecordId
            );
        }
        return r;
    }

    private static Result fromHttp(
        String service,
        CloudiatorHttp.Response res,
        String modalityIn,
        String modalityOut,
        String inputSummary,
        String relatedRecordId,
        Boolean extractAssistant
    ) {
        Result r = new Result();
        r.statusCode = res.statusCode;
        r.requestId = res.requestId;
        r.durationMs = res.durationMs;
        r.body = res.body;
        r.ok = res.statusCode != null && res.statusCode >= 200 && res.statusCode < 300;
        String output = res.body;
        String artifactId;
        if (r.ok && extractAssistant && res.json != null && res.json.containsKey('choices')) {
            try {
                List<Object> choices = (List<Object>) res.json.get('choices');
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> c0 = (Map<String, Object>) choices[0];
                    Map<String, Object> msg = (Map<String, Object>) c0.get('message');
                    if (msg != null) {
                        r.text = (String) msg.get('content');
                        output = r.text;
                    }
                }
            } catch (Exception ignore) {
            }
        }
        if (r.ok && res.json != null) {
            if (res.json.containsKey('artifact_id')) {
                artifactId = String.valueOf(res.json.get('artifact_id'));
            } else if (res.json.containsKey('id') && service == 'JobCreate') {
                r.text = String.valueOf(res.json.get('id'));
                output = r.text;
            }
            if (res.json.containsKey('result')) {
                Object resultNode = res.json.get('result');
                if (resultNode instanceof Map<String, Object>) {
                    Map<String, Object> resultMap = (Map<String, Object>) resultNode;
                    if (resultMap.containsKey('artifact_id')) {
                        artifactId = String.valueOf(resultMap.get('artifact_id'));
                    }
                }
            }
        }
        if (!r.ok) {
            r.errorMessage = res.body;
        }
        r.artifactId = artifactId;
        r.logId = CloudiatorLogger.log(
            service,
            r.ok,
            res,
            modalityIn,
            modalityOut,
            inputSummary,
            output,
            r.errorMessage,
            artifactId,
            relatedRecordId
        );
        return r;
    }
}
