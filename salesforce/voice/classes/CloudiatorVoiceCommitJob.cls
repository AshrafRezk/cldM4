/**
 * Commits finished Cloudiator voice calls on a schedule: every run lists the
 * calls that are ready, creates their records (CloudiatorVoiceCommit), and
 * acks them. A schedulable cannot call out, so it hands off to a Queueable.
 *
 * Every 15 minutes (Execute Anonymous, as a user with Cloudiator API access
 * and create rights on the target objects):
 *
 *   CloudiatorVoiceCommitJob.scheduleEvery15Minutes();
 */
public with sharing class CloudiatorVoiceCommitJob implements Schedulable {
    public static final String JOB_PREFIX = 'Cloudiator voice commit :';

    public void execute(SchedulableContext context) {
        System.enqueueJob(new Runner());
    }

    public class Runner implements Queueable, Database.AllowsCallouts {
        public void execute(QueueableContext context) {
            CloudiatorVoiceCommit.commitSessions(
                new List<CloudiatorVoiceCommit.Request>{ new CloudiatorVoiceCommit.Request() }
            );
        }
    }

    /** Four cron entries at :00, :15, :30, :45. Returns the job ids. */
    public static List<Id> scheduleEvery15Minutes() {
        List<Id> ids = new List<Id>();
        for (Integer minute = 0; minute < 60; minute += 15) {
            ids.add(System.schedule(JOB_PREFIX + minute, '0 ' + minute + ' * * * ?', new CloudiatorVoiceCommitJob()));
        }
        return ids;
    }
}
