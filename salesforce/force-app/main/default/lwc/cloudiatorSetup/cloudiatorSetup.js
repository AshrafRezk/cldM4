import { LightningElement, track } from 'lwc';
import getConfig from '@salesforce/apex/CloudiatorSetupController.getConfig';
import saveConfig from '@salesforce/apex/CloudiatorSetupController.saveConfig';
import testConnection from '@salesforce/apex/CloudiatorSetupController.testConnection';

export default class CloudiatorSetup extends LightningElement {
  @track loaded = false;
  @track busy = false;
  @track message = '';
  @track baseUrl = 'https://api.cloudiator.org';
  @track defaultModel = 'gemma4:e4b-it-qat';
  @track apiKey = '';
  @track useNamedCredential = false;
  @track hasApiKey = false;
  @track apiKeyLast4 = '';

  connectedCallback() {
    getConfig()
      .then((cfg) => {
        this.apply(cfg);
        this.loaded = true;
      })
      .catch((e) => {
        this.message = e.body && e.body.message ? e.body.message : String(e);
        this.loaded = true;
      });
  }

  apply(cfg) {
    this.baseUrl = cfg.baseUrl || this.baseUrl;
    this.defaultModel = cfg.defaultModel || this.defaultModel;
    this.useNamedCredential = !!cfg.useNamedCredential;
    this.hasApiKey = !!cfg.hasApiKey;
    this.apiKeyLast4 = cfg.apiKeyLast4 || '';
  }

  onChange(event) {
    const field = event.target.dataset.field;
    if (field === 'useNamedCredential') {
      this.useNamedCredential = event.target.checked;
    } else {
      this[field] = event.target.value;
    }
  }

  save() {
    this.busy = true;
    this.message = '';
    saveConfig({
      apiKey: this.apiKey,
      baseUrl: this.baseUrl,
      defaultModel: this.defaultModel,
      useNamedCredential: this.useNamedCredential
    })
      .then((cfg) => {
        this.apply(cfg);
        this.apiKey = '';
        this.message = 'Saved.';
      })
      .catch((e) => {
        this.message = e.body && e.body.message ? e.body.message : String(e);
      })
      .finally(() => {
        this.busy = false;
      });
  }

  test() {
    this.busy = true;
    this.message = '';
    testConnection()
      .then((r) => {
        this.message = r.ok
          ? `Health OK (HTTP ${r.statusCode}) request ${r.requestId || '—'}`
          : `Health failed: ${r.errorMessage || r.body}`;
      })
      .catch((e) => {
        this.message = e.body && e.body.message ? e.body.message : String(e);
      })
      .finally(() => {
        this.busy = false;
      });
  }
}
