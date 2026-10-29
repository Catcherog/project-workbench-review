"""Feishu card JSON 2.0 primitives; user text stays plain text."""
def plain(text):return {'tag':'plain_text','content':str(text)}

def paragraph(text):return {'tag':'div','text':plain(text)}

def button(label,value,*,name=None,submit=False):
    result={'tag':'button','text':plain(label),'type':'default','width':'fill',
            'behaviors':[{'type':'callback','value':value}]}
    if name:result['name']=name
    if submit:result['form_action_type']='submit'
    return result

def field(name,label,*,kind='input',options=None,default=None,required=True):
    item={'tag':kind,'name':name,'required':required,'width':'fill','placeholder':plain(label)}
    if options is not None:item['options']=[{'text':plain(label),'value':value} for value,label in options]
    if kind=='picker_datetime' and isinstance(default,str):default=default[:16]
    if default not in (None,'',[]):item['selected_values' if kind=='multi_select_static' else 'initial_option' if kind=='select_static' else 'initial_datetime' if kind=='picker_datetime' else 'default_value']=default
    if kind=='input':item.update(input_type='multiline_text',max_length=1000)
    return [paragraph(label),item]

def card(title,elements):
    return {'schema':'2.0','config':{'wide_screen_mode':True,'update_multi':True},
            'header':{'title':plain(title)},'body':{'direction':'vertical','elements':elements}}
