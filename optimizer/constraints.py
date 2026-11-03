"""Compile bounded integer linear constraints to QUBO; check original rules independently."""
import numpy as np


def slack_weights(limit):
    weights=[]
    while limit:
        value=min(1 << len(weights),limit)
        weights.append(value)
        limit-=value
    return weights


def compile_constraints(q,offset,rules):
    n=len(q)
    original_offset=offset
    # Exceeds the complete range of the original objective. Any integer violation costs at least P.
    penalty=float(np.abs(q).sum()+1)
    if not np.isfinite(penalty) or penalty>1e9:
        raise ValueError('constraint_coefficient_limit')
    terms=[]; count=n
    for rule in rules:
        a=np.asarray(rule.coefficients,dtype=float); rhs=rule.rhs
        ids=np.flatnonzero(a)
        # Forbidden binary pair needs no auxiliary variable.
        if rule.relation=='le' and rhs==1 and len(ids)==2 and np.all(a[ids]==1):
            terms.append(('pair',ids,None,None)); continue
        if rule.relation=='le' and rhs>=sum(max(0,x) for x in a): continue
        if rule.relation=='ge' and rhs<=sum(min(0,x) for x in a): continue
        if rule.relation=='ge': a=-a; rhs=-rhs
        weights=slack_weights(int(rhs-sum(min(0,x) for x in a))) if rule.relation!='eq' else []
        terms.append(('square',a,rhs,(count,weights)))
        count+=len(weights)
    if count>64: raise ValueError('comparison_size_limit')
    compiled=np.zeros((count,count)); compiled[:n,:n]=q; encoding=[]
    for kind,a,rhs,extra in terms:
        if kind=='pair':
            i,j=a; compiled[i,j]+=penalty/2; compiled[j,i]+=penalty/2
        else:
            v=np.zeros(count); v[:n]=a
            start,weights=extra; v[start:start+len(weights)]=weights
            encoding.append({'coefficients':[int(x) for x in v],'rhs':int(rhs)})
            compiled+=penalty*np.outer(v,v)
            compiled[np.diag_indices(count)]-=2*penalty*rhs*v
            offset+=penalty*rhs*rhs
    if not np.isfinite(compiled).all() or np.abs(compiled).max()>1e15 or abs(offset)>1e15:
        raise ValueError('constraint_coefficient_limit')
    return compiled,float(offset),{'decision_count':n,'auxiliary_bits':count-n,'penalty':penalty,
        'base_Q':q.tolist(),'base_offset':float(original_offset),
        'constraints':[r.model_dump() for r in rules],'constraint_encoding':encoding}


def check_constraints(bits,rules):
    checks=[]
    for rule in rules:
        r=rule.model_dump() if hasattr(rule,'model_dump') else rule
        actual=int(sum(a*b for a,b in zip(r['coefficients'],bits)))
        ok={'eq':actual==r['rhs'],'le':actual<=r['rhs'],'ge':actual>=r['rhs']}[r['relation']]
        checks.append({'label':r['label'],'actual':actual,'relation':r['relation'],'required':r['rhs'],'satisfied':bool(ok)})
    return checks
