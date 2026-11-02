import { LightningElement, track } from 'lwc';
import listServices from '@salesforce/apex/CloudiatorAppController.listServices';
import runChat from '@salesforce/apex/CloudiatorAppController.runChat';
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
