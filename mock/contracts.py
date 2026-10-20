"""Public argument types; contains no fixture IDs, dates or reference answers."""
import copy

def object_schema(properties, required=()):
    return {'type':'object', 'properties':properties, 'required':list(required), 'additionalProperties':False}

def argument_schemas(case_id, available):
    text = {'type':'string'}
    texts = {'type':'array', 'items':text}
    boolean = {'type':'boolean'}
    route = {'type':'array', 'items':object_schema({'id':text, 'organization':text, 'role':text},
                                                ('id','organization','role'))}
    editable = {'title':text, 'visibility':text, 'privacy_reasons':{'type':'array','items':{'type':'integer'}},
                'security':text, 'access_scope':text, 'approval_route':route, 'recipients':texts,
                'attachments':texts, 'auto_send':boolean, 'body':text}
    leave = {k:text for k in ('type','date','start','end','reason','destination','transport','expense')}
    leave.update(companions=texts, approval_route=route)
    window = 'window_id' if case_id=='NP-E-WXS-READ-05' else 'document_id'
    schemas = {
        'documents.query':object_schema({
            'scope':{'type':'string','enum':['my_documents','registry','circulation']},
            'role':{'type':'string','enum':['drafted','received','approved']},
            'from':text, 'to':text,
            'date_basis':{'type':'string','enum':['processed','registered']},
            'title_contains':text, 'drafter_id':text,
            'condition':{'type':'string','enum':['A','B','C']}, 'all_pages':boolean}, ('scope',)),
        'cbe.search':object_schema({'name':text,'scope':{'type':'string','enum':['auto','my','all']}}, ('name',)),
        'wxs.read':object_schema({window:text}, (window,)),
        'wxs.apply':object_schema({'fields':object_schema(editable)}, ('fields',)),
        'neis.prepare':object_schema({'fields':object_schema(leave, ('type','date','start','end','reason','approval_route'))}, ('fields',)),
    }
    return {name:copy.deepcopy(schema) for name,schema in schemas.items() if name in available}
