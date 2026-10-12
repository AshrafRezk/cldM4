/** Reads protected hierarchy custom setting for Cloudiator. */
public with sharing class CloudiatorConfig {
    public static final String DEFAULT_BASE = 'https://api.cloudiator.org';
    public static final String DEFAULT_MODEL = 'gemma4:e4b-it-qat';

    public class Settings {
        public String apiKey;
        public String baseUrl;
        public String defaultModel;
        public Boolean useNamedCredential;
    }

    public static Settings get() {
        Cloudiator_Config__c row = Cloudiator_Config__c.getOrgDefaults();
        Settings s = new Settings();
        s.apiKey = row == null ? null : row.Api_Key__c;
        s.baseUrl = (row == null || String.isBlank(row.Base_URL__c))
            ? DEFAULT_BASE
            : row.Base_URL__c.replaceAll('/$', '');
        s.defaultModel = (row == null || String.isBlank(row.Default_Model__c))
            ? DEFAULT_MODEL
            : row.Default_Model__c;
        s.useNamedCredential = row != null && row.Use_Named_Credential__c == true;
        return s;
    }

    public static void save(String apiKey, String baseUrl, String defaultModel, Boolean useNamedCredential) {
        Cloudiator_Config__c row = Cloudiator_Config__c.getOrgDefaults();
        if (row == null || row.Id == null) {
            row = new Cloudiator_Config__c(SetupOwnerId = UserInfo.getOrganizationId());
        }
        if (String.isNotBlank(apiKey)) {
            row.Api_Key__c = apiKey.trim();
        }
        if (String.isNotBlank(baseUrl)) {
            row.Base_URL__c = baseUrl.trim().replaceAll('/$', '');
        }
        if (String.isNotBlank(defaultModel)) {
            row.Default_Model__c = defaultModel.trim();
        }
        if (useNamedCredential != null) {
            row.Use_Named_Credential__c = useNamedCredential;
        }
        upsert row;
    }

    public static Boolean isConfigured() {
        Settings s = get();
        return String.isNotBlank(s.apiKey) || s.useNamedCredential == true;
    }
}
