/**
 * Publish Cloudiator_Voice_Script__c records to the appliance.
 *
 * With Question child records, the script JSON is built from them
 * (CloudiatorVoiceScriptBuilder) and written back to Definition__c so admins
 * can see exactly what was sent. Without questions, Definition__c is sent as
 * hand-written JSON, and External_Id__c, Inbound_Numbers__c and Active__c
 * override the same keys in it.
 *
 * After publishing, Files attached to questions (titled ar-EG / en-US) and to
 * the script (greeting.ar-EG, goodbye.en-US, ...) are uploaded as recordings
 * by a queued job, because Apex cannot call out after this transaction's DML.
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
            SELECT Id, Name, Definition__c, External_Id__c, Inbound_Numbers__c, Active__c,
                   Languages__c, Arabic_Greeting__c, English_Greeting__c, Arabic_Closing__c,
                   English_Closing__c, Arabic_Voice__c, English_Voice__c, Transcript_Field__c,
                   Record_Links__c, Fixed_Values__c, Variables__c, Personas__c, Beep__c, Hold_Music__c,
                   Arabic_Off_Script__c, English_Off_Script__c,
                   (SELECT Id, Order__c, Step_Key__c, Arabic_Text__c, English_Text__c, Target_Field__c,
                           Required__c, Max_Attempts__c, Announcement__c, Next_Key__c, Routes__c, Read_Back__c
                    FROM Questions__r ORDER BY Order__c),
                   (SELECT Id, FAQ_Key__c, Keywords__c, Arabic_Answer__c, English_Answer__c
                    FROM FAQs__r ORDER BY Name)
            FROM Cloudiator_Voice_Script__c
            WHERE Id IN :scriptRecordIds
            WITH USER_MODE
        ];
        Set<Id> published = new Set<Id>();
        for (Cloudiator_Voice_Script__c script : scripts) {
            Result r = new Result();
            r.scriptRecordId = script.Id;
            r.scriptId = script.External_Id__c;
            try {
                Map<String, Object> def = script.Questions__r.isEmpty()
                    ? definition(script)
                    : CloudiatorVoiceScriptBuilder.build(script, script.Questions__r, script.FAQs__r);
                String payload = JSON.serialize(def);
                if (!script.Questions__r.isEmpty()) {
                    script.Definition__c = JSON.serializePretty(def);
                }
                Map<String, Object> body = new Map<String, Object>{ 'definition' => payload };
                Map<String, Object> res = (Map<String, Object>) CloudiatorVoice.send(
                    'POST', '/v1/voice/scripts', body
                );
                r.version = Integer.valueOf(res.get('version'));
                script.Published_Version__c = r.version;
                script.Last_Publish_Error__c = null;
                published.add(script.Id);
            } catch (Exception e) {
                r.error = e.getMessage();
                script.Last_Publish_Error__c = r.error.left(255);
            }
            results.add(r);
        }
        // DML only after every callout: Apex forbids a callout after uncommitted work.
        update as user scripts;
        if (!published.isEmpty()) {
            System.enqueueJob(new CloudiatorVoiceRecordings(published));
        }
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
