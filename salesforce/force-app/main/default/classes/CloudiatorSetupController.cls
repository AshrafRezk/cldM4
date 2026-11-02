/** AuraEnabled setup for the Cloudiator Setup LWC. */
public with sharing class CloudiatorSetupController {
    public class ConfigView {
        @AuraEnabled public Boolean configured;
        @AuraEnabled public String baseUrl;
        @AuraEnabled public String defaultModel;
        @AuraEnabled public Boolean useNamedCredential;
        @AuraEnabled public Boolean hasApiKey;
        @AuraEnabled public String apiKeyLast4;
    }

    @AuraEnabled(cacheable=true)
    public static ConfigView getConfig() {
        CloudiatorConfig.Settings s = CloudiatorConfig.get();
        ConfigView v = new ConfigView();
        v.configured = CloudiatorConfig.isConfigured();
        v.baseUrl = s.baseUrl;
        v.defaultModel = s.defaultModel;
        v.useNamedCredential = s.useNamedCredential == true;
        v.hasApiKey = String.isNotBlank(s.apiKey);
        if (v.hasApiKey && s.apiKey.length() >= 4) {
            v.apiKeyLast4 = s.apiKey.substring(s.apiKey.length() - 4);
        }
        return v;
    }

    @AuraEnabled
    public static ConfigView saveConfig(String apiKey, String baseUrl, String defaultModel, Boolean useNamedCredential) {
        CloudiatorConfig.save(apiKey, baseUrl, defaultModel, useNamedCredential);
        return getConfig();
    }

    @AuraEnabled
    public static CloudiatorService.Result testConnection() {
        return CloudiatorService.health();
    }
}
