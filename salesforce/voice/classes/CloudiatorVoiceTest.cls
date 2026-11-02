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

    @IsTest
    static void templateBuildsLinkedPatientScript() {
        Id scriptId = CloudiatorVoiceTemplates.createOne('patient_support', null, 'psp-test');
        Cloudiator_Voice_Script__c script = [
            SELECT Id, Name, External_Id__c, Inbound_Numbers__c, Active__c, Languages__c,
                   Arabic_Greeting__c, English_Greeting__c, Arabic_Closing__c, English_Closing__c,
                   Arabic_Voice__c, English_Voice__c, Transcript_Field__c, Record_Links__c, Fixed_Values__c, Variables__c, Personas__c, Beep__c, Hold_Music__c,
                   (SELECT Id, Order__c, Step_Key__c, Arabic_Text__c, English_Text__c, Target_Field__c,
                           Required__c, Max_Attempts__c, Announcement__c, Next_Key__c, Routes__c FROM Questions__r ORDER BY Order__c)
            FROM Cloudiator_Voice_Script__c WHERE Id = :scriptId
        ];
        Map<String, Object> def = CloudiatorVoiceScriptBuilder.build(script, script.Questions__r);
        System.assertEquals('psp-test', def.get('id'));
        System.assertEquals(new List<String>{ 'ar-EG', 'en-US' }, def.get('languages'));
        List<Object> steps = (List<Object>) def.get('steps');
        System.assertEquals(6, steps.size(), 'greeting + 4 questions + goodbye');
        Map<String, Object> first = (Map<String, Object>) steps[1];
        System.assertEquals('full_name', first.get('key'));
        System.assertEquals('hangup', first.get('on_fail'));
        System.assert(((Map<String, Object>) first.get('say')).containsKey('en-US'));

        List<Object> records = (List<Object>) ((Map<String, Object>) def.get('commit')).get('records');
        Map<String, Object> contact = (Map<String, Object>) records[0];
        Map<String, Object> caseRec = (Map<String, Object>) records[1];
        System.assertEquals('Contact', contact.get('sobject'), 'parents first');
        System.assertEquals('{{full_name}}', ((Map<String, Object>) contact.get('fields')).get('LastName'));
        Map<String, Object> caseFields = (Map<String, Object>) caseRec.get('fields');
        System.assertEquals('{{Contact.Id}}', caseFields.get('ContactId'));
        System.assertEquals('{{transcript}}', caseFields.get('Description'));
        System.assertEquals('Phone', caseFields.get('Origin'));
        System.assertEquals(new List<String>{ 'Contact' }, caseRec.get('after'));
    }

    @IsTest
    static void everyTemplateBuilds() {
        for (String t : new List<String>{ 'case_intake', 'customer_onboarding' }) {
            Id scriptId = CloudiatorVoiceTemplates.createOne(t, null, null);
            Cloudiator_Voice_Script__c script = [
                SELECT Id, Name, External_Id__c, Inbound_Numbers__c, Active__c, Languages__c,
                       Arabic_Greeting__c, English_Greeting__c, Arabic_Closing__c, English_Closing__c,
                       Arabic_Voice__c, English_Voice__c, Transcript_Field__c, Record_Links__c, Fixed_Values__c, Variables__c, Personas__c, Beep__c, Hold_Music__c,
                       (SELECT Id, Order__c, Step_Key__c, Arabic_Text__c, English_Text__c, Target_Field__c,
                               Required__c, Max_Attempts__c, Announcement__c, Next_Key__c, Routes__c FROM Questions__r ORDER BY Order__c)
                FROM Cloudiator_Voice_Script__c WHERE Id = :scriptId
            ];
            Map<String, Object> def = CloudiatorVoiceScriptBuilder.build(script, script.Questions__r);
            System.assertEquals(t.replace('_', '-'), def.get('id'));
        }
        try {
            CloudiatorVoiceTemplates.createOne('nope', null, null);
            System.assert(false, 'expected a failure');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('Unknown template'));
        }
    }

    @IsTest
    static void builderRejectsMissingTextAndBadFields() {
        Cloudiator_Voice_Script__c script = new Cloudiator_Voice_Script__c(
            Name = 'x', External_Id__c = 'x', Languages__c = 'ar-EG;en-US',
            Arabic_Greeting__c = 'أهلاً', English_Greeting__c = 'Hi',
            Arabic_Closing__c = 'سلام', English_Closing__c = 'Bye'
        );
        Cloudiator_Voice_Question__c q = new Cloudiator_Voice_Question__c(
            Order__c = 1, Arabic_Text__c = 'اسمك؟', English_Text__c = null, Target_Field__c = 'Case.Subject'
        );
        try {
            CloudiatorVoiceScriptBuilder.build(script, new List<Cloudiator_Voice_Question__c>{ q });
            System.assert(false, 'expected missing English text');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('English'), e.getMessage());
        }
        q.English_Text__c = 'Name?';
        q.Target_Field__c = 'Subject';
        try {
            CloudiatorVoiceScriptBuilder.build(script, new List<Cloudiator_Voice_Question__c>{ q });
            System.assert(false, 'expected a bad field reference');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('Object.Field'), e.getMessage());
        }
        System.assertEquals(new List<String>{ 'en-US' }, CloudiatorVoiceScriptBuilder.languages('en-US'));
    }

    @IsTest
    static void recordingTitlesMapToLines() {
        System.assertEquals(new String[]{ 'q10', 'ar-EG' }, CloudiatorVoiceRecordings.lineFor('q10', 'ar-EG'));
        System.assertEquals(new String[]{ 'q10', 'en-US' }, CloudiatorVoiceRecordings.lineFor('q10', 'en'));
        System.assertEquals(new String[]{ 'greeting', 'ar-EG' }, CloudiatorVoiceRecordings.lineFor(null, 'Greeting.ar-eg'));
        System.assertEquals(null, CloudiatorVoiceRecordings.lineFor('q10', 'notes'));
        System.assertEquals(null, CloudiatorVoiceRecordings.lineFor(null, 'menu.ar-EG'));
    }

    @IsTest
    static void publishFromQuestionsUploadsRecordings() {
        Id scriptId = CloudiatorVoiceTemplates.createOne('case_intake', null, 'ci-test');
        Cloudiator_Voice_Question__c q = [SELECT Id FROM Cloudiator_Voice_Question__c WHERE Script__c = :scriptId ORDER BY Order__c LIMIT 1];
        ContentVersion file = new ContentVersion(Title = 'ar-EG', PathOnClient = 'ar-EG.m4a', VersionData = Blob.valueOf('audio'));
        insert file;
        Id docId = [SELECT ContentDocumentId FROM ContentVersion WHERE Id = :file.Id].ContentDocumentId;
        insert new ContentDocumentLink(ContentDocumentId = docId, LinkedEntityId = q.Id, ShareType = 'V');

        Mock mock = new Mock();
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        List<CloudiatorVoicePublish.Result> results = CloudiatorVoicePublish.publish(new List<Id>{ scriptId });
        Test.stopTest();
        System.assertEquals(null, results[0].error, results[0].error);
        Cloudiator_Voice_Script__c saved = [SELECT Definition__c FROM Cloudiator_Voice_Script__c WHERE Id = :scriptId];
        System.assert(saved.Definition__c.contains('full_name'), 'Definition__c shows what was sent');
        Boolean uploaded = false;
        for (String call : mock.calls) {
            uploaded = uploaded || call.contains('/recordings/full_name/ar-EG');
        }
        System.assert(uploaded, 'recording not uploaded: ' + mock.calls);
    }

    @IsTest
    static void variablesRoutesAndAnnouncementsBuild() {
        List<String> langs = new List<String>{ 'ar-EG', 'en-US' };
        Map<String, Object> vars = CloudiatorVoiceScriptBuilder.variables(
            'company = Acme Pharma\ncompany.ar = أكمي فارما\nprogram = Acme Care', langs);
        System.assertEquals('أكمي فارما', ((Map<String, Object>) vars.get('company')).get('ar-EG'));
        System.assertEquals('Acme Pharma', ((Map<String, Object>) vars.get('company')).get('en-US'));
        System.assertEquals('Acme Care', ((Map<String, Object>) vars.get('program')).get('ar-EG'));

        List<Object> routes = CloudiatorVoiceScriptBuilder.routes('new, جديد, أول مرة => new_name = New\nexisting, متابعة => case_number', 'Q');
        Map<String, Object> first = (Map<String, Object>) routes[0];
        System.assertEquals('new_name', first.get('next'));
        System.assertEquals('New', first.get('value'));
        System.assertEquals(3, ((List<String>) first.get('when')).size());
        System.assertEquals(null, ((Map<String, Object>) routes[1]).get('value'));
        try {
            CloudiatorVoiceScriptBuilder.routes('just words', 'Q');
            System.assert(false, 'expected a route format error');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('=>'), e.getMessage());
        }

        Cloudiator_Voice_Script__c script = new Cloudiator_Voice_Script__c(
            Name = 'Acme PSP', External_Id__c = 'acme-psp', Languages__c = 'ar-EG;en-US',
            Arabic_Greeting__c = 'أهلاً، معاك {{company}}.', English_Greeting__c = 'Hello, this is {{company}}.',
            Arabic_Closing__c = 'شكراً.', English_Closing__c = 'Thank you.',
            Variables__c = 'company = Acme Pharma\ncompany.ar = أكمي فارما'
        );
        List<Cloudiator_Voice_Question__c> qs = new List<Cloudiator_Voice_Question__c>{
            new Cloudiator_Voice_Question__c(Order__c = 10, Step_Key__c = 'hours', Announcement__c = true,
                Arabic_Text__c = 'مواعيدنا من ٩ لـ ٥.', English_Text__c = 'We are open nine to five.'),
            new Cloudiator_Voice_Question__c(Order__c = 20, Step_Key__c = 'menu', Next_Key__c = 'new_name',
                Arabic_Text__c = 'جديد ولا متابعة؟', English_Text__c = 'New or existing?',
                Routes__c = 'existing, متابعة => case_number = Follow-up'),
            new Cloudiator_Voice_Question__c(Order__c = 30, Step_Key__c = 'new_name', Next_Key__c = 'goodbye',
                Arabic_Text__c = 'اسمك؟', English_Text__c = 'Your name?'),
            new Cloudiator_Voice_Question__c(Order__c = 40, Step_Key__c = 'case_number',
                Arabic_Text__c = 'رقم الحالة؟', English_Text__c = 'Case number?')
        };
        Map<String, Object> def = CloudiatorVoiceScriptBuilder.build(script, qs);
        List<Object> steps = (List<Object>) def.get('steps');
        Map<String, Object> hours = (Map<String, Object>) steps[1];
        Map<String, Object> menu = (Map<String, Object>) steps[2];
        System.assertEquals(false, hours.get('gather'));
        System.assertEquals('menu', hours.get('next'));
        System.assertEquals('new_name', menu.get('next'), 'Next overrides order; also the no-match path');
        System.assertEquals(1, ((List<Object>) menu.get('routes')).size());
        System.assert(def.containsKey('variables'));
    }

    @IsTest
    static void personasParse() {
        List<String> langs = new List<String>{ 'ar-EG', 'en-US' };
        List<Object> people = CloudiatorVoiceScriptBuilder.personas('Mariam | مريم | Mariam\nAhmed | أحمد | Ahmed | Karim', langs);
        Map<String, Object> mariam = (Map<String, Object>) people[0];
        Map<String, Object> ahmed = (Map<String, Object>) people[1];
        System.assertEquals('mariam', mariam.get('id'));
        System.assertEquals('مريم', ((Map<String, Object>) mariam.get('name')).get('ar-EG'));
        System.assertEquals('Karim', ((Map<String, Object>) ahmed.get('voice')).get('en-US'));
        System.assertEquals('Ahmed', ((Map<String, Object>) ahmed.get('voice')).get('ar-EG'));
        try {
            CloudiatorVoiceScriptBuilder.personas('Mariam | مريم', langs);
            System.assert(false, 'expected a format error');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('voice'), e.getMessage());
        }
    }

    @IsTest
    static void faqBuilds() {
        List<String> langs = new List<String>{ 'ar-EG', 'en-US' };
        List<Object> out = CloudiatorVoiceScriptBuilder.faq(new List<Cloudiator_Voice_FAQ__c>{
            new Cloudiator_Voice_FAQ__c(FAQ_Key__c = 'food', Keywords__c = 'food, meal, أكل, جعان',
                Arabic_Answer__c = 'الدوا ده بيتاخد بعد الأكل.', English_Answer__c = 'Take it after a meal.'),
            new Cloudiator_Voice_FAQ__c(Keywords__c = 'hours',
                Arabic_Answer__c = 'من ٩ لـ ٥.', English_Answer__c = 'Nine to five.')
        }, langs);
        Map<String, Object> food = (Map<String, Object>) out[0];
        System.assertEquals('food', food.get('key'));
        System.assertEquals(4, ((List<String>) food.get('when')).size());
        System.assertEquals('faq2', ((Map<String, Object>) out[1]).get('key'));
        try {
            CloudiatorVoiceScriptBuilder.faq(new List<Cloudiator_Voice_FAQ__c>{
                new Cloudiator_Voice_FAQ__c(Arabic_Answer__c = 'x', English_Answer__c = 'y') }, langs);
            System.assert(false, 'expected a missing-keyword error');
        } catch (CloudiatorVoiceScriptBuilder.BuildException e) {
            System.assert(e.getMessage().contains('keyword'), e.getMessage());
        }
    }
}
