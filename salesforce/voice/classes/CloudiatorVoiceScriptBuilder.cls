/**
 * Builds the appliance's script JSON from a Cloudiator_Voice_Script__c and its
 * Cloudiator_Voice_Question__c records, so admins edit questions as records:
 *
 *   greeting -> question 1 .. question N -> closing (then hang up)
 *
 * Each question's Target_Field__c ("Case.Subject") becomes a field on the
 * commit record for that object with the caller's answer. Fixed_Values__c,
 * Transcript_Field__c and Record_Links__c fill in the rest. The appliance
 * validates the result again; this class only shapes it.
 */
public with sharing class CloudiatorVoiceScriptBuilder {
    public class BuildException extends Exception {}

    private static final Pattern FIELD_REF = Pattern.compile('^([A-Za-z][A-Za-z0-9_]*)\\.([A-Za-z][A-Za-z0-9_]*)$');
    private static final Pattern KEY = Pattern.compile('^[A-Za-z_][A-Za-z0-9_]{0,39}$');

    public static Map<String, Object> build(Cloudiator_Voice_Script__c script, List<Cloudiator_Voice_Question__c> questions) {
        return build(script, questions, new List<Cloudiator_Voice_FAQ__c>());
    }

    public static Map<String, Object> build(
        Cloudiator_Voice_Script__c script, List<Cloudiator_Voice_Question__c> questions, List<Cloudiator_Voice_FAQ__c> faqs
    ) {
        List<String> languages = languages(script.Languages__c);
        List<Cloudiator_Voice_Question__c> ordered = sortByOrder(questions);
        if (ordered.isEmpty()) {
            throw new BuildException('Add at least one question.');
        }

        List<Object> steps = new List<Object>();
        List<String> keys = new List<String>();
        for (Cloudiator_Voice_Question__c q : ordered) {
            String key = String.isNotBlank(q.Step_Key__c) ? q.Step_Key__c.trim() : 'q' + Integer.valueOf(q.Order__c);
            if (!KEY.matcher(key).matches() || keys.contains(key)) {
                throw new BuildException('Question ' + q.Order__c + ': answer key "' + key + '" is invalid or repeated.');
            }
            keys.add(key);
        }

        String firstQuestion = keys[0];
        steps.add(new Map<String, Object>{
            'key' => 'greeting', 'gather' => false, 'next' => firstQuestion,
            'say' => localized(languages, script.Arabic_Greeting__c, script.English_Greeting__c, 'Greeting')
        });
        for (Integer i = 0; i < ordered.size(); i++) {
            Cloudiator_Voice_Question__c q = ordered[i];
            String fallthrough = i + 1 < ordered.size() ? keys[i + 1] : 'goodbye';
            Map<String, Object> step = new Map<String, Object>{
                'key' => keys[i],
                'next' => String.isNotBlank(q.Next_Key__c) ? q.Next_Key__c.trim() : fallthrough,
                'say' => localized(languages, q.Arabic_Text__c, q.English_Text__c, 'Question ' + q.Order__c)
            };
            if (q.Announcement__c == true) {
                step.put('gather', false);
                if (String.isNotBlank(q.Routes__c)) {
                    throw new BuildException('Question ' + q.Order__c + ': an announcement cannot have routes.');
                }
            } else {
                Integer attempts = q.Max_Attempts__c == null ? 2 : Math.max(1, Math.min(5, Integer.valueOf(q.Max_Attempts__c)));
                step.put('gather', true);
                step.put('max_attempts', attempts);
                step.put('on_fail', q.Required__c == true ? 'hangup' : 'continue');
                if (q.Read_Back__c == true) {
                    step.put('confirm', true);
                }
                List<Object> routeList = routes(q.Routes__c, 'Question ' + q.Order__c);
                if (!routeList.isEmpty()) {
                    step.put('routes', routeList);
                }
            }
            steps.add(step);
        }
        steps.add(new Map<String, Object>{
            'key' => 'goodbye', 'gather' => false, 'next' => null,
            'say' => localized(languages, script.Arabic_Closing__c, script.English_Closing__c, 'Closing')
        });

        Map<String, Object> voices = new Map<String, Object>();
        for (String lang : languages) {
            String voice = lang.startsWith('ar') ? script.Arabic_Voice__c : script.English_Voice__c;
            if (String.isNotBlank(voice)) {
                voices.put(lang, voice.trim());
            }
        }

        Map<String, Object> def = new Map<String, Object>{
            'id' => script.External_Id__c.trim(),
            'display_name' => script.Name,
            'languages' => languages,
            'voices' => voices,
            'variables' => variables(script.Variables__c, languages),
            'personas' => personas(script.Personas__c, languages),
            'beep' => script.Beep__c != false,
            'hold_music' => script.Hold_Music__c != false,
            'inbound_numbers' => numbers(script.Inbound_Numbers__c),
            'active' => script.Active__c == true,
            'steps' => steps,
            'commit' => new Map<String, Object>{ 'records' => records(script, ordered, keys) }
        };
        if (faqs != null && !faqs.isEmpty()) {
            def.put('faq', faq(faqs, languages));
        }
        if (String.isNotBlank(script.Arabic_Off_Script__c) || String.isNotBlank(script.English_Off_Script__c)) {
            def.put('off_script_say', localized(languages, script.Arabic_Off_Script__c, script.English_Off_Script__c, 'Off-script reply'));
        }
        return def;
    }

    @TestVisible
    private static List<Object> faq(List<Cloudiator_Voice_FAQ__c> faqs, List<String> languages) {
        List<Object> out = new List<Object>();
        Set<String> keys = new Set<String>();
        Integer n = 0;
        for (Cloudiator_Voice_FAQ__c f : faqs) {
            n++;
            String key = String.isNotBlank(f.FAQ_Key__c) ? f.FAQ_Key__c.trim() : 'faq' + n;
            if (!KEY.matcher(key).matches() || keys.contains(key)) {
                throw new BuildException('FAQ key "' + key + '" is invalid or repeated.');
            }
            keys.add(key);
            List<String> words = new List<String>();
            for (String w : (f.Keywords__c == null ? '' : f.Keywords__c).split(',')) {
                if (String.isNotBlank(w)) {
                    words.add(w.trim());
                }
            }
            if (words.isEmpty()) {
                throw new BuildException('FAQ "' + key + '" needs at least one keyword.');
            }
            out.add(new Map<String, Object>{
                'key' => key, 'when' => words,
                'say' => localized(languages, f.Arabic_Answer__c, f.English_Answer__c, 'FAQ ' + key)
            });
        }
        return out;
    }

    @TestVisible
    private static List<Object> records(Cloudiator_Voice_Script__c script, List<Cloudiator_Voice_Question__c> ordered, List<String> keys) {
        // object -> field -> template, in first-seen order
        Map<String, Map<String, Object>> fields = new Map<String, Map<String, Object>>();
        List<String> objectOrder = new List<String>();

        for (Integer i = 0; i < ordered.size(); i++) {
            if (String.isNotBlank(ordered[i].Target_Field__c)) {
                String[] ref = fieldRef(ordered[i].Target_Field__c, 'Question ' + ordered[i].Order__c);
                put(fields, objectOrder, ref[0], ref[1], '{{' + keys[i] + '}}');
            }
        }
        if (String.isNotBlank(script.Transcript_Field__c)) {
            String[] ref = fieldRef(script.Transcript_Field__c, 'Transcript Field');
            put(fields, objectOrder, ref[0], ref[1], '{{transcript}}');
        }
        if (String.isNotBlank(script.Fixed_Values__c)) {
            for (String line : script.Fixed_Values__c.split('\n')) {
                line = line.trim();
                if (String.isBlank(line)) {
                    continue;
                }
                Integer eq = line.indexOf('=');
                if (eq < 1) {
                    throw new BuildException('Fixed value "' + line + '" must be Object.Field=Value.');
                }
                String[] ref = fieldRef(line.substring(0, eq).trim(), 'Fixed value');
                put(fields, objectOrder, ref[0], ref[1], line.substring(eq + 1).trim());
            }
        }

        // Child.Lookup=Parent: the child waits for the parent's Id.
        Map<String, List<String>> parentsOf = new Map<String, List<String>>();
        if (String.isNotBlank(script.Record_Links__c)) {
            for (String link : script.Record_Links__c.split(';')) {
                link = link.trim();
                if (String.isBlank(link)) {
                    continue;
                }
                Integer eq = link.indexOf('=');
                if (eq < 1) {
                    throw new BuildException('Record link "' + link + '" must be Child.LookupField=Parent.');
                }
                String[] ref = fieldRef(link.substring(0, eq).trim(), 'Record link');
                String parent = link.substring(eq + 1).trim();
                if (!fields.containsKey(parent)) {
                    throw new BuildException('Record link parent "' + parent + '" gets no fields from any question or fixed value.');
                }
                put(fields, objectOrder, ref[0], ref[1], '{{' + parent + '.Id}}');
                if (!parentsOf.containsKey(ref[0])) {
                    parentsOf.put(ref[0], new List<String>());
                }
                parentsOf.get(ref[0]).add(parent);
            }
        }

        // Parents before children (a simple stable topological pass).
        List<String> sorted = new List<String>();
        Integer guard = 0;
        while (sorted.size() < objectOrder.size()) {
            if (guard++ > objectOrder.size() + 1) {
                throw new BuildException('Record links loop back on themselves.');
            }
            for (String obj : objectOrder) {
                if (sorted.contains(obj)) {
                    continue;
                }
                Boolean ready = true;
                for (String parent : parentsOf.containsKey(obj) ? parentsOf.get(obj) : new List<String>()) {
                    ready = ready && sorted.contains(parent);
                }
                if (ready) {
                    sorted.add(obj);
                }
            }
        }

        List<Object> out = new List<Object>();
        for (String obj : sorted) {
            out.add(new Map<String, Object>{
                'sobject' => obj,
                'fields' => fields.get(obj),
                'after' => parentsOf.containsKey(obj) ? parentsOf.get(obj) : new List<String>()
            });
        }
        return out;
    }

    /** "new, جديد, أول مرة => new_case = New" per line. */
    @TestVisible
    private static List<Object> routes(String raw, String where) {
        List<Object> out = new List<Object>();
        if (String.isBlank(raw)) {
            return out;
        }
        for (String line : raw.split('\n')) {
            line = line.trim();
            if (String.isBlank(line)) {
                continue;
            }
            Integer arrow = line.indexOf('=>');
            if (arrow < 1) {
                throw new BuildException(where + ': route "' + line + '" must be keywords => next key.');
            }
            List<String> keywords = new List<String>();
            for (String k : line.substring(0, arrow).split(',')) {
                if (String.isNotBlank(k)) {
                    keywords.add(k.trim());
                }
            }
            String target = line.substring(arrow + 2).trim();
            String value = null;
            Integer eq = target.indexOf('=');
            if (eq > 0) {
                value = target.substring(eq + 1).trim();
                target = target.substring(0, eq).trim();
            }
            if (keywords.isEmpty() || !KEY.matcher(target).matches()) {
                throw new BuildException(where + ': route "' + line + '" needs keywords and a next key.');
            }
            Map<String, Object> route = new Map<String, Object>{ 'when' => keywords, 'next' => target };
            if (String.isNotBlank(value)) {
                route.put('value', value);
            }
            out.add(route);
        }
        return out;
    }

    /** "Mariam | مريم | Mariam" (English name | Arabic name | voice [| English voice]) per line. */
    @TestVisible
    private static List<Object> personas(String raw, List<String> languages) {
        List<Object> out = new List<Object>();
        if (String.isBlank(raw)) {
            return out;
        }
        Set<String> ids = new Set<String>();
        for (String line : raw.split('\n')) {
            if (String.isBlank(line)) {
                continue;
            }
            List<String> parts = new List<String>();
            for (String part : line.split('\\|')) {
                parts.add(part.trim());
            }
            if (parts.size() < 3 || String.isBlank(parts[0]) || String.isBlank(parts[1]) || String.isBlank(parts[2])) {
                throw new BuildException('Persona "' + line.trim() + '" must be English name | Arabic name | voice.');
            }
            String id = parts[0].toLowerCase().replaceAll('[^a-z0-9_]', '_');
            if (!KEY.matcher(id).matches() || ids.contains(id)) {
                throw new BuildException('Persona "' + parts[0] + '" needs a unique English name.');
            }
            ids.add(id);
            Map<String, Object> names = new Map<String, Object>();
            Map<String, Object> voices = new Map<String, Object>();
            for (String lang : languages) {
                Boolean arabic = lang.startsWith('ar');
                names.put(lang, arabic ? parts[1] : parts[0]);
                voices.put(lang, !arabic && parts.size() > 3 && String.isNotBlank(parts[3]) ? parts[3] : parts[2]);
            }
            out.add(new Map<String, Object>{ 'id' => id, 'name' => names, 'voice' => voices });
        }
        return out;
    }

    /** "company = Acme" for every language; "company.ar = أكمي" / "company.en = Acme" per language. */
    @TestVisible
    private static Map<String, Object> variables(String raw, List<String> languages) {
        Map<String, Map<String, Object>> values = new Map<String, Map<String, Object>>();
        if (String.isBlank(raw)) {
            return new Map<String, Object>();
        }
        for (String line : raw.split('\n')) {
            line = line.trim();
            if (String.isBlank(line)) {
                continue;
            }
            Integer eq = line.indexOf('=');
            if (eq < 1) {
                throw new BuildException('Variable "' + line + '" must be name = value.');
            }
            String name = line.substring(0, eq).trim();
            String value = line.substring(eq + 1).trim();
            String only = null;
            if (name.endsWith('.ar') || name.endsWith('.en')) {
                only = name.right(2);
                name = name.left(name.length() - 3);
            }
            if (!KEY.matcher(name).matches()) {
                throw new BuildException('Variable name "' + name + '" must be letters, digits or _.');
            }
            if (!values.containsKey(name)) {
                values.put(name, new Map<String, Object>());
            }
            for (String lang : languages) {
                if (only == null ? !values.get(name).containsKey(lang) : lang.startsWith(only)) {
                    values.get(name).put(lang, value);
                }
            }
        }
        Map<String, Object> out = new Map<String, Object>();
        for (String name : values.keySet()) {
            out.put(name, values.get(name));
        }
        return out;
    }

    private static void put(Map<String, Map<String, Object>> fields, List<String> order, String obj, String field, String value) {
        if (!fields.containsKey(obj)) {
            fields.put(obj, new Map<String, Object>());
            order.add(obj);
        }
        fields.get(obj).put(field, value);
    }

    private static String[] fieldRef(String value, String where) {
        Matcher m = FIELD_REF.matcher(value.trim());
        if (!m.matches()) {
            throw new BuildException(where + ': "' + value + '" must look like Object.Field (e.g. Case.Subject).');
        }
        return new String[]{ m.group(1), m.group(2) };
    }

    @TestVisible
    private static List<String> languages(String raw) {
        List<String> out = new List<String>();
        for (String part : (String.isBlank(raw) ? 'ar-EG;en-US' : raw).split('[;,]')) {
            String lang = part.trim();
            if (String.isNotBlank(lang) && !out.contains(lang)) {
                if (!lang.startsWith('ar') && !lang.startsWith('en')) {
                    throw new BuildException('Language "' + lang + '": only Arabic (ar-..) and English (en-..) have text fields.');
                }
                out.add(lang);
            }
        }
        return out;
    }

    private static Map<String, Object> localized(List<String> languages, String arabic, String english, String where) {
        Map<String, Object> out = new Map<String, Object>();
        for (String lang : languages) {
            String text = lang.startsWith('ar') ? arabic : english;
            if (String.isBlank(text)) {
                throw new BuildException(where + ' needs ' + (lang.startsWith('ar') ? 'Arabic' : 'English') + ' text.');
            }
            out.put(lang, text.trim());
        }
        return out;
    }

    private static List<String> numbers(String raw) {
        List<String> out = new List<String>();
        if (String.isNotBlank(raw)) {
            for (String n : raw.split(',')) {
                if (String.isNotBlank(n)) {
                    out.add(n.trim());
                }
            }
        }
        return out;
    }

    private static List<Cloudiator_Voice_Question__c> sortByOrder(List<Cloudiator_Voice_Question__c> questions) {
        List<Cloudiator_Voice_Question__c> sorted = new List<Cloudiator_Voice_Question__c>();
        List<Decimal> orders = new List<Decimal>();
        Map<Decimal, List<Cloudiator_Voice_Question__c>> byOrder = new Map<Decimal, List<Cloudiator_Voice_Question__c>>();
        for (Cloudiator_Voice_Question__c q : questions == null ? new List<Cloudiator_Voice_Question__c>() : questions) {
            if (!byOrder.containsKey(q.Order__c)) {
                byOrder.put(q.Order__c, new List<Cloudiator_Voice_Question__c>());
                orders.add(q.Order__c);
            }
            byOrder.get(q.Order__c).add(q);
        }
        orders.sort();
        for (Decimal o : orders) {
            sorted.addAll(byOrder.get(o));
        }
        return sorted;
    }
}
