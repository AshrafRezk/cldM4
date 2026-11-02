/**
 * Publish Cloudiator_Voice_Script__c records to the appliance.
 * External_Id__c, Inbound_Numbers__c and Active__c override the same keys in
 * Definition__c, so admins can repoint a number without editing JSON.
 */
public with sharing class CloudiatorVoicePublish {
    // One callout per script; keep a Flow from looping 50 callouts in one transaction.
    public static final Integer MAX_PER_CALL = 10;

    public class Result {
        @InvocableVariable public Id scriptRecordId;
        @InvocableVariable public String scriptId;
        @InvocableVariable public Integer version;
        @InvocableVariable public String error;
    }

    @InvocableMethod(label='Publish Cloudiator voice script' callout=true
        description='Sends Definition__c to POST /v1/voice/scripts.')
    public static List<Result> publish(List<Id> scriptRecordIds) {
        List<Result> results = new List<Result>();
        if (scriptRecordIds == null || scriptRecordIds.isEmpty()) {
            return results;
        }
        if (scriptRecordIds.size() > MAX_PER_CALL) {
            throw new CloudiatorVoice.CalloutFailure('Publish at most ' + MAX_PER_CALL + ' scripts at a time.');
        }
        List<Cloudiator_Voice_Script__c> scripts = [
            SELECT Id, Definition__c, External_Id__c, Inbound_Numbers__c, Active__c
            FROM Cloudiator_Voice_Script__c
            WHERE Id IN :scriptRecordIds
            WITH USER_MODE
        ];
        for (Cloudiator_Voice_Script__c script : scripts) {
            Result r = new Result();
            r.scriptRecordId = script.Id;
            r.scriptId = script.External_Id__c;
            try {
                Map<String, Object> body = new Map<String, Object>{
                    'definition' => JSON.serialize(definition(script))
                };
                Map<String, Object> res = (Map<String, Object>) CloudiatorVoice.send(
                    'POST', '/v1/voice/scripts', body
                );
                r.version = Integer.valueOf(res.get('version'));
                script.Published_Version__c = r.version;
                script.Last_Publish_Error__c = null;
            } catch (Exception e) {
                r.error = e.getMessage();
                script.Last_Publish_Error__c = r.error.left(255);
            }
            results.add(r);
        }
        // DML only after every callout: Apex forbids a callout after uncommitted work.
        update as user scripts;
        return results;
    }

    public static Map<String, Object> definition(Cloudiator_Voice_Script__c script) {
        Map<String, Object> def = String.isBlank(script.Definition__c)
            ? new Map<String, Object>()
            : (Map<String, Object>) JSON.deserializeUntyped(script.Definition__c);
        if (String.isNotBlank(script.External_Id__c)) {
            def.put('id', script.External_Id__c.trim());
        }
        if (String.isNotBlank(script.Inbound_Numbers__c)) {
            List<String> numbers = new List<String>();
            for (String n : script.Inbound_Numbers__c.split(',')) {
                if (String.isNotBlank(n)) {
                    numbers.add(n.trim());
                }
            }
            def.put('inbound_numbers', numbers);
        }
        def.put('active', script.Active__c == true);
        return def;
    }
}
