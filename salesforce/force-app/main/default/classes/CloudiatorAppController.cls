/** AuraEnabled helpers for Cloudiator Home / service runner. */
public with sharing class CloudiatorAppController {
    public class ServiceInfo {
        @AuraEnabled public String name;
        @AuraEnabled public String label;
        @AuraEnabled public String path;
        @AuraEnabled public String modalityIn;
        @AuraEnabled public String modalityOut;
        @AuraEnabled public String description;
        @AuraEnabled public Boolean flowInvocable;
    }

    @AuraEnabled(cacheable=true)
    public static List<ServiceInfo> listServices() {
        List<ServiceInfo> out = new List<ServiceInfo>();
        out.add(info('Chat', 'Chat completions', '/v1/chat/completions', 'Text', 'Text', 'OpenAI-compatible chat (stream forced off).', true));
        out.add(info('Embeddings', 'Embeddings', '/v1/embeddings', 'Text', 'Binary', 'nomic-embed-text vectors.', true));
        out.add(info('OCR', 'OCR', '/v1/tools/ocr', 'Image', 'Text', 'Apple Vision OCR; image URL or base64.', true));
        out.add(info('Geocode', 'Geocode', '/v1/tools/geocode', 'Text', 'Text', 'Nominatim geocoding.', true));
        out.add(info('Research', 'Research', '/v1/tools/research', 'Text', 'Text', 'Public web research snippets.', true));
        out.add(info('Chart', 'Chart', '/v1/tools/chart', 'Text', 'Image', 'Matplotlib/plotly chart → artifact URL.', true));
        out.add(info('Stats', 'Stats', '/v1/tools/stats', 'Text', 'Text', 'Deterministic stats on JSON rows.', true));
        out.add(info('Query', 'Query (DuckDB)', '/v1/tools/query', 'Text', 'Text', 'SQL over JSON rows.', true));
        out.add(info('Document', 'Document', '/v1/tools/document', 'Binary', 'Mixed', 'PDF/DOCX/XLSX extract or render.', true));
        out.add(info('Text', 'Text tools', '/v1/tools/text', 'Text', 'Text', 'Fuzzy match, phone parse, etc.', true));
        out.add(info('Time', 'Time / holidays', '/v1/tools/time', 'Text', 'Text', 'Timezone and holiday helpers.', true));
        out.add(info('ImageOps', 'Image ops', '/v1/tools/image', 'Image', 'Image', 'Resize/convert/QR (not FLUX).', true));
        out.add(info('JobCreate', 'Image job (FLUX)', '/v1/jobs', 'Text', 'Image', 'Requires image_generation scope. Poll with JobPoll.', true));
        out.add(info('JobPoll', 'Poll job', '/v1/jobs/{id}', 'None', 'Mixed', 'One poll per transaction.', true));
        out.add(info('Health', 'Health', '/v1/health', 'None', 'Text', 'Local appliance health (no Neon).', false));
        return out;
    }

    @AuraEnabled
    public static CloudiatorService.Result runChat(String prompt, String model) {
        return CloudiatorService.chat(prompt, model, 512, null);
    }

    @AuraEnabled
    public static CloudiatorService.Result runTool(String serviceName, String jsonBody) {
        Map<String, Object> payload = String.isBlank(jsonBody)
            ? new Map<String, Object>()
            : (Map<String, Object>) JSON.deserializeUntyped(jsonBody);
        String path;
        String modalityIn = 'Text';
        String modalityOut = 'Text';
        if (serviceName == 'OCR') { path = '/v1/tools/ocr'; modalityIn = 'Image'; }
        else if (serviceName == 'Geocode') { path = '/v1/tools/geocode'; }
        else if (serviceName == 'Research') { path = '/v1/tools/research'; }
        else if (serviceName == 'Chart') { path = '/v1/tools/chart'; modalityOut = 'Image'; }
        else if (serviceName == 'Stats') { path = '/v1/tools/stats'; }
        else if (serviceName == 'Query') { path = '/v1/tools/query'; }
        else if (serviceName == 'Document') { path = '/v1/tools/document'; modalityIn = 'Binary'; modalityOut = 'Mixed'; }
        else if (serviceName == 'Text') { path = '/v1/tools/text'; }
        else if (serviceName == 'Time') { path = '/v1/tools/time'; }
        else if (serviceName == 'ImageOps') { path = '/v1/tools/image'; modalityIn = 'Image'; modalityOut = 'Image'; }
        else if (serviceName == 'Embeddings') { return CloudiatorService.embeddings((String) payload.get('input'), null); }
        else { throw new AuraHandledException('Unknown service: ' + serviceName); }
        return CloudiatorService.tool(serviceName, path, payload, modalityIn, modalityOut, null);
    }

    @AuraEnabled(cacheable=true)
    public static List<Cloudiator_Call_Log__c> recentLogs(Integer maxRows) {
        Integer lim = maxRows == null || maxRows < 1 ? 25 : Math.min(maxRows, 200);
        return [
            SELECT Id, Name, Service__c, Status__c, Http_Status__c, Request_Id__c,
                   Modality_In__c, Modality_Out__c, Duration_Ms__c, Artifact_Id__c,
                   Input_Summary__c, Output_Summary__c, Error_Message__c, CreatedDate
            FROM Cloudiator_Call_Log__c
            ORDER BY CreatedDate DESC
            LIMIT :lim
        ];
    }

    private static ServiceInfo info(String name, String label, String path, String mi, String mo, String desc, Boolean flowable) {
        ServiceInfo s = new ServiceInfo();
        s.name = name; s.label = label; s.path = path;
        s.modalityIn = mi; s.modalityOut = mo; s.description = desc; s.flowInvocable = flowable;
        return s;
    }
}
