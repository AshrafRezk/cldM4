/**
 * Starter voice scripts an admin creates in one click and then edits:
 *
 *  case_intake          Case only (web-to-case style Supplied* fields)
 *  patient_support      Contact + Case linked to it
 *  customer_onboarding  Lead
 *
 * Arabic lines are written in Egyptian colloquial Arabic, the way an agent in
 * Cairo would say them, not Modern Standard Arabic.
 */
public with sharing class CloudiatorVoiceTemplates {
    public class Request {
        @InvocableVariable(required=true description='case_intake, patient_support, or customer_onboarding')
        public String template;
        @InvocableVariable(description='Script name. Defaults to the template title.')
        public String name;
        @InvocableVariable(description='Script id on the appliance. Defaults to the template name.')
        public String scriptId;
    }

    public class Result {
        @InvocableVariable public Id scriptRecordId;
    }

    private class Q {
        String key; String ar; String en; String target; Boolean required;
        Q(String key, String ar, String en, String target, Boolean required) {
            this.key = key; this.ar = ar; this.en = en; this.target = target; this.required = required;
        }
        // Numbers are read back to the caller; names and free text are not.
        Boolean readBack() { return target != null && (target.endsWith('Phone') || key == 'mobile'); }
    }

    @InvocableMethod(label='Create Cloudiator voice script from template'
        description='Creates a script with Egyptian Arabic and English questions mapped to CRM fields.')
    public static List<Result> create(List<Request> requests) {
        List<Result> results = new List<Result>();
        for (Request req : requests) {
            Result r = new Result();
            r.scriptRecordId = createOne(req.template, req.name, req.scriptId);
            results.add(r);
        }
        return results;
    }

    public static Id createOne(String template, String name, String scriptId) {
        Cloudiator_Voice_Script__c script = new Cloudiator_Voice_Script__c(
            Languages__c = 'ar-EG;en-US', Active__c = true
        );
        List<Q> questions;
        String title;
        if (template == 'case_intake') {
            title = 'Case intake';
            script.Arabic_Greeting__c = 'أهلاً بيك في خدمة العملاء. المكالمة دي متسجلة علشان نقدر نساعدك أحسن.';
            script.English_Greeting__c = 'Welcome to customer care. This call is recorded so we can help you better.';
            script.Arabic_Closing__c = 'شكراً ليك. سجلنا طلبك، وحد من فريقنا هيكلمك قريب.';
            script.English_Closing__c = 'Thank you. We have logged your request and someone from our team will call you soon.';
            script.Transcript_Field__c = 'Case.Description';
            script.Fixed_Values__c = 'Case.Origin=Phone\nCase.Status=New';
            questions = new List<Q>{
                new Q('full_name', 'ممكن تقولي اسمك بالكامل؟', 'May I have your full name, please?', 'Case.SuppliedName', true),
                new Q('mobile', 'إيه رقم الموبايل اللي نقدر نكلمك عليه؟', 'What is the best mobile number to reach you on?', 'Case.SuppliedPhone', true),
                new Q('issue', 'قولي في جملة واحدة، المشكلة إيه؟', 'In one sentence, what is the issue?', 'Case.Subject', true),
                new Q('details', 'ممكن تحكيلي تفاصيل أكتر؟ زي إمتى حصلت أو رقم الطلب لو موجود.', 'Can you tell me more, like when it happened or an order number if you have one?', null, false)
            };
        } else if (template == 'patient_support') {
            title = 'Patient support';
            script.Arabic_Greeting__c = 'أهلاً بيك في برنامج دعم المرضى. المكالمة دي متسجلة، وبياناتك هتفضل سرية.';
            script.English_Greeting__c = 'Welcome to the patient support program. This call is recorded and your information is kept confidential.';
            script.Arabic_Closing__c = 'شكراً ليك. ممرضة من البرنامج هتتواصل معاك في أقرب وقت. لو حالتك طارئة، كلم الإسعاف على طول.';
            script.English_Closing__c = 'Thank you. A nurse from the program will contact you shortly. If this is an emergency, call an ambulance right away.';
            script.Transcript_Field__c = 'Case.Description';
            script.Record_Links__c = 'Case.ContactId=Contact';
            script.Fixed_Values__c = 'Case.Origin=Phone\nCase.Status=New\nCase.Subject=Patient support call';
            questions = new List<Q>{
                new Q('full_name', 'ممكن تقولي اسمك بالكامل؟', 'May I have your full name, please?', 'Contact.LastName', true),
                new Q('mobile', 'إيه رقم موبايلك؟', 'What is your mobile number?', 'Contact.MobilePhone', true),
                new Q('treatment', 'إنت بتتصل بخصوص أنهي دوا أو علاج؟', 'Which medication or treatment are you calling about?', null, false),
                new Q('symptoms', 'عندك أي أعراض أو آثار جانبية حابب تبلغنا بيها؟', 'Are you having any symptoms or side effects you would like to report?', null, false)
            };
        } else if (template == 'customer_onboarding') {
            title = 'Customer onboarding';
            script.Arabic_Greeting__c = 'أهلاً بيك! هنسألك كام سؤال سريع علشان نبدأ نفتحلك الحساب.';
            script.English_Greeting__c = 'Welcome! We will ask a few quick questions to get your account started.';
            script.Arabic_Closing__c = 'تمام كده! فريقنا هيكلمك علشان نكمل فتح الحساب. نورتنا.';
            script.English_Closing__c = 'All set! Our team will call you to finish setting up your account. Thank you.';
            script.Transcript_Field__c = 'Lead.Description';
            script.Fixed_Values__c = 'Lead.LeadSource=Phone Inquiry';
            questions = new List<Q>{
                new Q('full_name', 'ممكن تقولي اسمك بالكامل؟', 'May I have your full name, please?', 'Lead.LastName', true),
                new Q('company', 'إيه اسم الشركة أو النشاط بتاعك؟', 'What is the name of your company or business?', 'Lead.Company', true),
                new Q('mobile', 'إيه رقم الموبايل اللي نقدر نكلمك عليه؟', 'What is the best mobile number to reach you on?', 'Lead.MobilePhone', true),
                new Q('city', 'إنت في أنهي مدينة؟', 'Which city are you in?', 'Lead.City', false)
            };
        } else {
            throw new CloudiatorVoiceScriptBuilder.BuildException(
                'Unknown template "' + template + '". Use case_intake, patient_support, or customer_onboarding.'
            );
        }
        script.Name = String.isNotBlank(name) ? name : title;
        script.External_Id__c = String.isNotBlank(scriptId) ? scriptId : template.replace('_', '-');
        insert as user script;

        List<Cloudiator_Voice_Question__c> rows = new List<Cloudiator_Voice_Question__c>();
        for (Integer i = 0; i < questions.size(); i++) {
            Q q = questions[i];
            rows.add(new Cloudiator_Voice_Question__c(
                Script__c = script.Id, Order__c = (i + 1) * 10, Step_Key__c = q.key,
                Arabic_Text__c = q.ar, English_Text__c = q.en, Target_Field__c = q.target,
                Required__c = q.required, Max_Attempts__c = q.readBack() ? 3 : 2, Read_Back__c = q.readBack()
            ));
        }
        insert as user rows;
        return script.Id;
    }
}
