/** Writes Cloudiator_Call_Log__c rows (best-effort; never fails the callout path). */
public without sharing class CloudiatorLogger {
    public static Id log(
        String service,
        Boolean ok,
        CloudiatorHttp.Response res,
        String modalityIn,
        String modalityOut,
        String inputSummary,
        String outputSummary,
        String errorMessage,
        String artifactId,
        String relatedRecordId
    ) {
        try {
            Cloudiator_Call_Log__c row = new Cloudiator_Call_Log__c();
            row.Service__c = service;
            row.Status__c = ok ? 'Success' : 'Failure';
            row.Modality_In__c = modalityIn;
            row.Modality_Out__c = modalityOut;
            if (res != null) {
                row.Http_Status__c = res.statusCode;
                row.Request_Id__c = res.requestId;
                row.Duration_Ms__c = res.durationMs;
            }
            row.Input_Summary__c = clip(inputSummary, 12000);
            row.Output_Summary__c = clip(outputSummary, 12000);
            row.Error_Message__c = clip(errorMessage, 8000);
            row.Artifact_Id__c = artifactId;
            row.Related_Record_Id__c = relatedRecordId;
            insert row;
            return row.Id;
        } catch (Exception e) {
            System.debug(LoggingLevel.WARN, 'CloudiatorLogger failed: ' + e.getMessage());
            return null;
        }
    }

    private static String clip(String value, Integer maxLen) {
        if (String.isBlank(value)) {
            return value;
        }
        return value.length() <= maxLen ? value : value.substring(0, maxLen);
    }
}
