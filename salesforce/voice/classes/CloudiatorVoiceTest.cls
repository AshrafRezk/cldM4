@IsTest
private class CloudiatorVoiceTest {
    private static final String COMMIT_JSON = JSON.serialize(new Map<String, Object>{
        'records' => new List<Object>{
            new Map<String, Object>{
                'sobject' => 'Lead',
                'fields' => new Map<String, Object>{
                    'LastName' => 'Sara Ahmed', 'Company' => 'Phone Intake', 'Phone' => '01012345678'
                },
                'after' => new List<Object>()
            },
            new Map<String, Object>{
                'sobject' => 'Task',
                'fields' => new Map<String, Object>{
                    'Subject' => 'Inbound voice intake', 'Status' => 'Completed', 'WhoId' => '{{Lead.Id}}'
                },
                'after' => new List<Object>{ 'Lead' }
            }
        }
    });

    private class Mock implements HttpCalloutMock {
        public List<String> calls = new List<String>();

        public HttpResponse respond(HttpRequest req) {
            calls.add(req.getMethod() + ' ' + req.getEndpoint());
            HttpResponse res = new HttpResponse();
            res.setHeader('X-Request-Id', 'test');
            res.setStatusCode(200);
            String url = req.getEndpoint();
            if (url.endsWith('/v1/voice/scripts')) {
                res.setBody('{"id":"intake-ar","version":3}');
            } else if (url.contains('/v1/voice/sessions?status=ready_to_commit')) {
                res.setBody(JSON.serialize(new Map<String, Object>{
                    'data' => new List<Object>{ session() }
                }));
            } else if (url.endsWith('/ack')) {
                res.setBody('{"id":"s1","status":"committed"}');
            } else {
                res.setBody(JSON.serialize(session()));
            }
            return res;
        }
    }

    private static Map<String, Object> session() {
        return new Map<String, Object>{
            'id' => 's1', 'status' => 'ready_to_commit', 'commit_json' => COMMIT_JSON
        };
    }

    @IsTest
    static void publishSendsDefinitionAndRecordsVersion() {
        Cloudiator_Voice_Script__c script = new Cloudiator_Voice_Script__c(
            Name = 'Intake', External_Id__c = 'intake-ar', Active__c = true,
            Inbound_Numbers__c = '+201000000001, +201000000002',
            Definition__c = '{"steps":[{"key":"hi","say":"Hello","next":null}]}'
        );
        insert script;
        Map<String, Object> def = CloudiatorVoicePublish.definition(script);
        System.assertEquals('intake-ar', def.get('id'));
        System.assertEquals(2, ((List<Object>) def.get('inbound_numbers')).size());

        Test.setMock(HttpCalloutMock.class, new Mock());
        Test.startTest();
        List<CloudiatorVoicePublish.Result> results =
            CloudiatorVoicePublish.publish(new List<Id>{ script.Id });
        Test.stopTest();
        System.assertEquals(null, results[0].error);
        System.assertEquals(3, results[0].version);
        System.assertEquals(3, [SELECT Published_Version__c FROM Cloudiator_Voice_Script__c].Published_Version__c.intValue());
    }

    @IsTest
    static void commitInsertsLeadThenTaskAndAcks() {
        Mock mock = new Mock();
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        List<CloudiatorVoiceCommit.Result> results =
            CloudiatorVoiceCommit.commitSessions(new List<CloudiatorVoiceCommit.Request>());
        Test.stopTest();
        System.assertEquals(null, results[0].error, results[0].error);
        Lead lead = [SELECT Id, LastName FROM Lead];
        Task task = [SELECT WhoId FROM Task];
        System.assertEquals('Sara Ahmed', lead.LastName);
        System.assertEquals(lead.Id, task.WhoId);
        Boolean acked = false;
        for (String call : mock.calls) {
            acked = acked || call.endsWith('/v1/voice/sessions/s1/ack');
        }
        System.assert(acked, 'ack was not sent: ' + mock.calls);
    }

    @IsTest
    static void commitByIdRollsBackABadSession() {
        Test.setMock(HttpCalloutMock.class, new Mock());
        CloudiatorVoiceCommit.Request req = new CloudiatorVoiceCommit.Request();
        req.sessionId = 's1';
        Test.startTest();
        List<CloudiatorVoiceCommit.Result> results =
            CloudiatorVoiceCommit.commitSessions(new List<CloudiatorVoiceCommit.Request>{ req });
        Test.stopTest();
        System.assertEquals(null, results[0].error, results[0].error);

        try {
            CloudiatorVoiceCommit.insertRecords(
                '{"records":[{"sobject":"Task","fields":{"WhoId":"{{Lead.Id}}"},"after":[]}]}'
            );
            System.assert(false, 'expected a failure');
        } catch (CloudiatorVoice.CalloutFailure e) {
            System.assert(e.getMessage().contains('Lead.Id'));
        }
    }

    @IsTest
    static void coerceHandlesTypes() {
        System.assertEquals(true, CloudiatorVoiceCommit.coerce(Lead.HasOptedOutOfEmail.getDescribe(), 'true'));
        System.assertEquals(null, CloudiatorVoiceCommit.coerce(Lead.LastName.getDescribe(), '  '));
        String longName = 'x'.repeat(200);
        System.assertEquals(80, ((String) CloudiatorVoiceCommit.coerce(Lead.LastName.getDescribe(), longName)).length());
    }
}
