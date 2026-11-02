/**
 * Uploads a person's recordings to the appliance after a publish.
 *
 *  - A File on a Question titled "ar-EG" or "en-US" (any extension) is that
 *    question's audio in that language.
 *  - A File on the Script titled "greeting.ar-EG", "goodbye.en-US", ... is the
 *    greeting or closing.
 *
 * The newest version of each File wins. Lines without a recording keep the
 * appliance's generated Egyptian/English voice.
 */
public with sharing class CloudiatorVoiceRecordings implements Queueable, Database.AllowsCallouts {
    // Leave headroom under the 100-callouts-per-transaction limit.
    public static final Integer MAX_UPLOADS = 90;
    private static final Pattern LANG = Pattern.compile('^(?i)(ar|en)(-[A-Za-z]{2})?$');

    private final Set<Id> scriptIds;

    public CloudiatorVoiceRecordings(Set<Id> scriptIds) {
        this.scriptIds = scriptIds;
    }

    public void execute(QueueableContext context) {
        Map<Id, Cloudiator_Voice_Script__c> scripts = new Map<Id, Cloudiator_Voice_Script__c>([
            SELECT Id, External_Id__c, Languages__c,
                   (SELECT Id, Order__c, Step_Key__c FROM Questions__r)
            FROM Cloudiator_Voice_Script__c WHERE Id IN :scriptIds
        ]);
        // record Id -> (script, step key)
        Map<Id, String[]> targets = new Map<Id, String[]>();
        for (Cloudiator_Voice_Script__c s : scripts.values()) {
            targets.put(s.Id, new String[]{ s.External_Id__c, null });
            for (Cloudiator_Voice_Question__c q : s.Questions__r) {
                String key = String.isNotBlank(q.Step_Key__c) ? q.Step_Key__c.trim() : 'q' + Integer.valueOf(q.Order__c);
                targets.put(q.Id, new String[]{ s.External_Id__c, key });
            }
        }
        if (targets.isEmpty()) {
            return;
        }
        List<Id> recordIds = new List<Id>(targets.keySet());
        List<ContentDocumentLink> links = [
            SELECT LinkedEntityId, ContentDocument.LatestPublishedVersionId, ContentDocument.Title
            FROM ContentDocumentLink WHERE LinkedEntityId IN :recordIds
        ];
        Map<Id, String[]> paths = new Map<Id, String[]>();  // version Id -> [script, step, lang]
        for (ContentDocumentLink link : links) {
            String[] target = targets.get(link.LinkedEntityId);
            String[] line = lineFor(target[1], link.ContentDocument.Title);
            if (line != null && paths.size() < MAX_UPLOADS) {
                paths.put(link.ContentDocument.LatestPublishedVersionId, new String[]{ target[0], line[0], line[1] });
            }
        }
        if (paths.isEmpty()) {
            return;
        }
        Set<Id> versionIds = paths.keySet();
        for (ContentVersion version : [SELECT Id, VersionData FROM ContentVersion WHERE Id IN :versionIds]) {
            String[] p = paths.get(version.Id);
            String path = '/v1/voice/scripts/' + EncodingUtil.urlEncode(p[0], 'UTF-8')
                + '/recordings/' + p[1] + '/' + p[2];
            try {
                CloudiatorVoice.sendBlob('PUT', path, version.VersionData, 'application/octet-stream');
            } catch (Exception e) {
                System.debug(LoggingLevel.WARN, 'recording upload failed for ' + path + ': ' + e.getMessage());
            }
        }
    }

    /** [step key, language] for a File title, or null when the title is not a recording name. */
    @TestVisible
    private static String[] lineFor(String questionKey, String title) {
        if (String.isBlank(title)) {
            return null;
        }
        String t = title.trim();
        if (questionKey != null) {
            return LANG.matcher(t).matches() ? new String[]{ questionKey, canonical(t) } : null;
        }
        Integer dot = t.indexOf('.');
        if (dot < 1) {
            return null;
        }
        String step = t.substring(0, dot).toLowerCase();
        String lang = t.substring(dot + 1);
        if ((step == 'greeting' || step == 'goodbye') && LANG.matcher(lang).matches()) {
            return new String[]{ step, canonical(lang) };
        }
        return null;
    }

    private static String canonical(String lang) {
        String base = lang.substring(0, 2).toLowerCase();
        if (lang.length() > 2) {
            return base + '-' + lang.substring(3).toUpperCase();
        }
        return base == 'ar' ? 'ar-EG' : 'en-US';
    }
}
