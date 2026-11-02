import { LightningElement, track } from 'lwc';
import listServices from '@salesforce/apex/CloudiatorAppController.listServices';
import runChat from '@salesforce/apex/CloudiatorAppController.runChat';
import runTool from '@salesforce/apex/CloudiatorAppController.runTool';
import recentLogs from '@salesforce/apex/CloudiatorAppController.recentLogs';

const COLUMNS = [
  { label: 'Number', fieldName: 'Name', type: 'text' },
  { label: 'Service', fieldName: 'Service__c', type: 'text' },
  { label: 'Status', fieldName: 'Status__c', type: 'text' },
  { label: 'HTTP', fieldName: 'Http_Status__c', type: 'number' },
  { label: 'Request Id', fieldName: 'Request_Id__c', type: 'text' },
  { label: 'When', fieldName: 'CreatedDate', type: 'date' }
];

export default class CloudiatorHome extends LightningElement {
  @track services = [];
  @track logs = [];
  @track prompt = '';
  @track chatResult = '';
  @track busy = false;
  @track voiceScripts = [];
  @track voiceResult = '';
  columns = COLUMNS;

  connectedCallback() {
    listServices().then((rows) => {
      this.services = rows || [];
    });
    this.reloadLogs();
  }

  reloadLogs() {
    recentLogs({ maxRows: 25 }).then((rows) => {
      this.logs = rows || [];
    });
  }

  onPrompt(event) {
    this.prompt = event.target.value;
  }

  message(e) {
    return e && e.body && e.body.message ? e.body.message : String(e);
  }

  loadVoiceScripts() {
    this.busy = true;
    this.voiceResult = '';
    runTool({ serviceName: 'VoiceScripts', jsonBody: null })
      .then((r) => {
        if (!r.ok) {
          // 403 here means the key lacks the voice scope: tick it in the console under Keys → Scopes.
          this.voiceResult = r.errorMessage || r.body;
          return;
        }
        const rows = (JSON.parse(r.body || '{}').data || []);
        this.voiceScripts = rows.map((s) => ({ id: s.id, label: (s.display_name || s.id) + ' (v' + s.version + ')' }));
        this.voiceResult = rows.length ? '' : 'No voice scripts published yet.';
        this.reloadLogs();
      })
      .catch((e) => {
        this.voiceResult = this.message(e);
      })
      .finally(() => {
        this.busy = false;
      });
  }

  callLink(event) {
    this.busy = true;
    this.voiceResult = '';
    runTool({ serviceName: 'VoiceCallLink', jsonBody: JSON.stringify({ script_id: event.target.dataset.id }) })
      .then((r) => {
        this.voiceResult = r.ok ? JSON.parse(r.body).url + '\n(shown once: store it now)' : r.errorMessage || r.body;
        this.reloadLogs();
      })
      .catch((e) => {
        this.voiceResult = this.message(e);
      })
      .finally(() => {
        this.busy = false;
      });
  }

  runChat() {
    this.busy = true;
    this.chatResult = '';
    runChat({ prompt: this.prompt, model: null })
      .then((r) => {
        this.chatResult = r.ok ? r.text || r.body : r.errorMessage || r.body;
        this.reloadLogs();
      })
      .catch((e) => {
        this.chatResult = e.body && e.body.message ? e.body.message : String(e);
      })
      .finally(() => {
        this.busy = false;
      });
  }
}
