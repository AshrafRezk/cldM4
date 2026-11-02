/**
 * Insert the CRM records a finished call produced, then ack them.
 *
 * Order per transaction: callouts (fetch sessions) -> DML (inserts) ->
 * Queueable (ack callouts). Apex forbids a callout after uncommitted DML, so
 * the ack cannot happen inline. Inserts run in USER_MODE: CRUD and FLS of the
 * running user apply, and only sObjects named in the session's own
 * commit.records are ever touched.
 */
public with sharing class CloudiatorVoiceCommit {
    public static final Integer MAX_SESSIONS = 10;
    private static final Pattern PARENT_ID = Pattern.compile('\\{\\{([A-Za-z][A-Za-z0-9_]*)\\.Id\\}\\}');

    public class Request {
        @InvocableVariable(description='Session id. Blank = commit every ready_to_commit session (up to 10).')
        public String sessionId;
    }

    public class Result {
        @InvocableVariable public String sessionId;
        @InvocableVariable public String recordIdsJson;
        @InvocableVariable public String error;
    }

    @InvocableMethod(label='Commit Cloudiator voice sessions' callout=true
        description='Creates the Lead/Case/Task records from finished calls and acks them.')
    public static List<Result> commitSessions(List<Request> requests) {
        List<Map<String, Object>> sessions = fetch(requests);
        List<Result> results = new List<Result>();
        Map<String, Map<String, String>> acks = new Map<String, Map<String, String>>();
        for (Map<String, Object> session : sessions) {
            Result r = new Result();
            r.sessionId = (String) session.get('id');
            Savepoint sp = Database.setSavepoint();
            try {
                Map<String, String> ids = insertRecords((String) session.get('commit_json'));
                r.recordIdsJson = JSON.serialize(ids);
                acks.put(r.sessionId, ids);
            } catch (Exception e) {
                Database.rollback(sp);
                r.error = e.getMessage();
            }
            results.add(r);
        }
        if (!acks.isEmpty()) {
            System.enqueueJob(new AckJob(acks));
        }
        return results;
    }

    private static List<Map<String, Object>> fetch(List<Request> requests) {
        List<Map<String, Object>> sessions = new List<Map<String, Object>>();
        List<String> ids = new List<String>();
        for (Request req : requests == null ? new List<Request>() : requests) {
            if (req != null && String.isNotBlank(req.sessionId)) {
                ids.add(req.sessionId);
            }
        }
        if (ids.isEmpty()) {
            Map<String, Object> listed = (Map<String, Object>) CloudiatorVoice.send(
                'GET', '/v1/voice/sessions?status=ready_to_commit', null
            );
            for (Object item : (List<Object>) listed.get('data')) {
                if (sessions.size() == MAX_SESSIONS) {
                    break;
                }
                sessions.add((Map<String, Object>) item);
            }
            return sessions;
        }
        if (ids.size() > MAX_SESSIONS) {
            throw new CloudiatorVoice.CalloutFailure('Commit at most ' + MAX_SESSIONS + ' sessions at a time.');
        }
        for (String sessionId : ids) {
            Map<String, Object> session = (Map<String, Object>) CloudiatorVoice.send(
                'GET', '/v1/voice/sessions/' + EncodingUtil.urlEncode(sessionId, 'UTF-8'), null
            );
            if (session.get('status') == 'ready_to_commit') {
                sessions.add(session);
            }
        }
        return sessions;
    }

    @TestVisible
    private static Map<String, String> insertRecords(String commitJson) {
        Map<String, Object> doc = (Map<String, Object>) JSON.deserializeUntyped(commitJson);
        Map<String, String> inserted = new Map<String, String>();
        for (Object item : (List<Object>) doc.get('records')) {
            Map<String, Object> spec = (Map<String, Object>) item;
            String sobjectName = (String) spec.get('sobject');
            Schema.SObjectType type = Schema.getGlobalDescribe().get(sobjectName);
            if (type == null) {
                throw new CloudiatorVoice.CalloutFailure('Unknown sObject ' + sobjectName);
            }
            SObject record = type.newSObject();
            Map<String, Schema.SObjectField> fieldMap = type.getDescribe().fields.getMap();
            Map<String, Object> fields = (Map<String, Object>) spec.get('fields');
            for (String fieldName : fields.keySet()) {
                Schema.SObjectField field = fieldMap.get(fieldName);
                if (field == null) {
                    throw new CloudiatorVoice.CalloutFailure('Unknown field ' + sobjectName + '.' + fieldName);
                }
                String value = resolveParents((String) fields.get(fieldName), inserted);
                record.put(field, coerce(field.getDescribe(), value));
            }
            Database.insert(record, AccessLevel.USER_MODE);
            inserted.put(sobjectName, record.Id);
        }
        return inserted;
    }

    private static String resolveParents(String value, Map<String, String> inserted) {
        if (value == null) {
            return null;
        }
        Matcher m = PARENT_ID.matcher(value);
        String out = value;
        while (m.find()) {
            String parent = m.group(1);
            if (!inserted.containsKey(parent)) {
                throw new CloudiatorVoice.CalloutFailure(parent + '.Id is used before ' + parent + ' is inserted.');
            }
            out = out.replace(m.group(0), inserted.get(parent));
        }
        return out;
    }

    @TestVisible
    private static Object coerce(Schema.DescribeFieldResult field, String value) {
        if (String.isBlank(value)) {
            return null;
        }
        switch on field.getType() {
            when BOOLEAN { return Boolean.valueOf(value.trim()); }
            when INTEGER { return Integer.valueOf(value.trim()); }
            when DOUBLE, CURRENCY, PERCENT { return Decimal.valueOf(value.trim()); }
            when DATE { return Date.valueOf(value.trim()); }
            when DATETIME { return Datetime.valueOfGmt(value.trim().replace('T', ' ').removeEnd('Z')); }
            when else {
                Integer max = field.getLength();
                return (max > 0 && value.length() > max) ? value.left(max) : value;
            }
        }
    }

    public class AckJob implements Queueable, Database.AllowsCallouts {
        private Map<String, Map<String, String>> acks;

        public AckJob(Map<String, Map<String, String>> acks) {
            this.acks = acks;
        }

        public void execute(QueueableContext context) {
            for (String sessionId : acks.keySet()) {
                CloudiatorVoice.send(
                    'POST',
                    '/v1/voice/sessions/' + EncodingUtil.urlEncode(sessionId, 'UTF-8') + '/ack',
                    new Map<String, Object>{ 'record_ids' => acks.get(sessionId) }
                );
            }
        }
    }
}
