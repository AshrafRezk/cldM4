@IsTest
private class CloudiatorVoiceCommitJobTest {
    private class EmptyMock implements HttpCalloutMock {
        public Integer calls = 0;
        public HttpResponse respond(HttpRequest req) {
            calls++;
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setHeader('X-Request-Id', 'test');
            res.setBody('{"object":"list","data":[]}');
            return res;
        }
    }

    @IsTest
    static void schedulesFourRuns() {
        Test.startTest();
        List<Id> ids = CloudiatorVoiceCommitJob.scheduleEvery15Minutes();
        Test.stopTest();
        System.assertEquals(4, ids.size());
        System.assertEquals(4, [SELECT COUNT() FROM CronTrigger WHERE Id IN :ids]);
    }

    @IsTest
    static void runnerListsReadySessions() {
        EmptyMock mock = new EmptyMock();
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        System.enqueueJob(new CloudiatorVoiceCommitJob.Runner());
        Test.stopTest();
        System.assertEquals(1, mock.calls, 'one list call; nothing to commit');
    }

    @IsTest
    static void scheduledExecuteQueuesTheRunner() {
        Test.setMock(HttpCalloutMock.class, new EmptyMock());  // the queued runner calls out at stopTest
        Test.startTest();
        new CloudiatorVoiceCommitJob().execute(null);
        System.assertEquals(1, Limits.getQueueableJobs());
        Test.stopTest();
    }
}
