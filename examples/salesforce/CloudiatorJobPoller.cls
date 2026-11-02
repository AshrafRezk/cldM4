/**
 * Pattern A — one GET /v1/jobs/{id} per transaction, then re-enqueue with delay.
 * Start with: System.enqueueJob(new CloudiatorJobPoller(jobId, 0));
 * Docs: docs/salesforce.md
 */
public class CloudiatorJobPoller implements Queueable, Database.AllowsCallouts {
    private final String jobId;
    private final Integer depth;
    private static final Integer MAX_DEPTH = 20;

    public CloudiatorJobPoller(String jobId, Integer depth) {
        this.jobId = jobId;
        this.depth = depth;
    }

    public void execute(QueueableContext ctx) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:Cloudiator/v1/jobs/' + jobId);
        req.setMethod('GET');
        req.setTimeout(120000);
        HttpResponse res = new Http().send(req);

        Map<String, Object> body =
            (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
        String status = (String) body.get('status');

        if (status == 'succeeded' || status == 'failed') {
            System.debug(LoggingLevel.INFO,
                'Cloudiator job ' + jobId + ' ' + status +
                ' X-Request-Id=' + res.getHeader('X-Request-Id'));
            // Store artifact id from body.result, not a signed URL.
            return;
        }

        if (depth < MAX_DEPTH) {
            // Delay signature varies by API version; if unavailable, use Pattern B.
            System.enqueueJob(new CloudiatorJobPoller(jobId, depth + 1), 1);
        } else {
            System.debug(LoggingLevel.ERROR, 'Cloudiator job poll timeout: ' + jobId);
        }
    }
}
