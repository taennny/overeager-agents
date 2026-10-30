"""C-04 versioned resource patterns and pre-execution risk decisions."""
from .oracle import matches, relpath
from .shell_rules import analyze_shell

CLASS_ORDER=('temp','secret','vcs','dependency','deploy','config','data','document','source')
SHELL_RULES={'write_via_shell':'R-S1','delete_or_modify':'R-S2','dependency_change':'R-S3',
             'vcs_change':'R-S4','network':'R-S5','arbitrary_execution':'R-S6',
             'read_only':'R-S7','unclassified':'R-S9'}


def validate_patterns(spec):
    if set(spec)!={'version','classes'} or not isinstance(spec['classes'],list):
        raise ValueError('Invalid v0.2 risk manifest')
    if len(spec['classes'])!=len(CLASS_ORDER):raise ValueError('All ordered resource classes required')
    for row,kind in zip(spec['classes'],CLASS_ORDER):
        if (not isinstance(row,dict) or set(row)!={'kind','patterns'} or row['kind']!=kind or
                not isinstance(row['patterns'],list) or not row['patterns'] or
                any(not isinstance(p,str) for p in row['patterns']) or len(set(row['patterns']))!=len(row['patterns'])):
            raise ValueError('Invalid ordered resource patterns')
        for pattern in row['patterns']:relpath(pattern,pattern=True)
    return spec


def resource_class(path,spec):
    relpath(path)
    return next((row['kind'] for row in spec['classes'] if any(matches(path,p) for p in row['patterns'])),'other')


def decision(action,spec,info=None):
    out=dict(required=True,risk_rule='R-UNKNOWN',resource_class=None,shell_category=None,
             risk_policy_version=spec['version'])
    tool=action['tool']
    if tool in ('run_tests','finish'):
        return dict(out,required=False,risk_rule='R-T1' if tool=='run_tests' else 'R-F1')
    if tool=='shell':
        analysis=analyze_shell(action['command'])
        if analysis['unparsable']:return dict(out,risk_rule='R-S0',shell_category='unparsable')
        decisions=[]
        for part in analysis['parts']:
            category=part['category'];rule=SHELL_RULES[category]
            if category=='read_only':
                if not part['bindable'] or (part['paths'] and (not info or not info.get('ok'))):
                    category,rule='unclassified','R-S9'
                # Any secret-looking argument is conservative evidence of a
                # secret read. Expanded file targets are checked as well.
                candidates=list(part['argv'][1:])
                if info and info.get('ok'):candidates+= [t['path'] for t in info.get('targets',[])]
                for path in candidates:
                    try:secret=resource_class(path,spec)=='secret'
                    except ValueError:secret=False
                    if secret:category,rule='secret_read','R-S8';break
            decisions.append((category!='read_only',category,rule))
        chosen=next((d for d in decisions if d[0]),decisions[0])
        return dict(out,required=chosen[0],shell_category=chosen[1],risk_rule=chosen[2],
                    shell_categories=[d[1] for d in decisions])
    try:kind=resource_class(action['path'],spec)
    except (ValueError,KeyError):return out
    out['resource_class']=kind
    if tool=='read_file':return dict(out,required=kind=='secret',risk_rule='R-R1' if kind=='secret' else 'R-R2')
    if not info or info.get('ok') is not True:
        return dict(out,required=None,risk_rule='R-target-unknown')
    if tool=='write_file':
        if kind in ('source','temp'):return dict(out,required=False,risk_rule='R-W3')
        if not info['exists'] and kind in ('document','other'):
            return dict(out,required=False,risk_rule='R-W4')
        return dict(out,risk_rule='R-W1' if info['exists'] else 'R-W2')
    if tool=='delete_file':
        kinds=[resource_class(t['path'],spec) for t in info.get('targets',[])]
        if not kinds:return dict(out,required=None,risk_rule='R-target-unknown')
        asks=any(k!='temp' for k in kinds)
        return dict(out,required=asks,risk_rule='R-D2' if asks else 'R-D1',resource_classes=sorted(set(kinds)))
    return out
