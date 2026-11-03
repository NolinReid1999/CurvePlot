"""Result-page presentation language; never rename source data or evaluate formulas."""
import re
import json

PARAMETERS={
    'slope':'Slope','intercept':'Intercept','amplitude':'Amplitude','sigma':'Width σ',
    'center':'Center','fwhm':'FWHM','height':'Height','area':'Area','offset':'Baseline',
    'frequency':'Angular frequency ω','frequency_cycles':'Frequency','period':'Period',
    'shift':'Phase φ','decay':'Time constant τ','origin':'Time origin','rate':'Rate',
    'exponent':'Exponent','breakpoint':'Breakpoint','breakpoint2':'Second breakpoint',
    'delta':'Slope change','delta2':'Second slope change',
}
STATISTICS={'均值':'Mean','中位数':'Median','标准差':'Standard deviation','标准误':'Standard error',
    '最小值':'Minimum','最大值':'Maximum','有效点数':'Valid points','积分':'Integral',
    '斜率':'Slope','截距':'Intercept','斜率标准误':'Slope standard error','起点X':'Start X','终点X':'End X',
    '最小值X':'X at minimum','最大值X':'X at maximum','有效次数N':'Valid repetitions',
    'mean':'Mean','median':'Median','std':'Standard deviation','sem':'Standard error',
    'min':'Minimum','max':'Maximum','count':'Valid points',
    '上包络均值':'Mean upper envelope','下包络均值':'Mean lower envelope'}
CATEGORIES={'描述统计':'Descriptive statistics','基础数学':'Basic mathematics','平滑与校正':'Smoothing and correction',
    '数据预处理':'Data preprocessing','交互区域分析':'Region analysis','信号分析':'Signal analysis',
    '包络':'Envelope','重复测量':'Replicate measurements'}
METHODS={'statistics':'Descriptive statistics','derivative':'Derivative · dy/dx','integral':'Integral · ∫y dx',
    'cumulative':'Cumulative integral','interpolate':'Interpolation','resample':'Resampling',
    'add':'Addition · α + β','subtract_columns':'Subtraction · α − β','multiply':'Multiplication · α × β',
    'divide':'Division · α / β','subtract':'Reference subtraction','moving_average':'Moving average',
    'savgol':'Savitzky–Golay smoothing','block_average':'Block averaging','baseline_constant':'Constant baseline subtraction',
    'baseline_linear':'Linear baseline subtraction','normalize_max':'Maximum-absolute normalization',
    'normalize_range':'0–1 normalization','fft_amplitude':'FFT · one-sided amplitude spectrum',
    'fft_power':'FFT · power spectral density','lowpass':'Low-pass filter','highpass':'High-pass filter',
    'bandpass':'Band-pass filter','bandstop':'Band-stop filter','region_stats':'Region statistics',
    'region_integral':'Definite integral / area','region_slope':'Linear slope','extrema':'Extrema and positions',
    'envelope_hilbert':'Hilbert amplitude envelope','envelope_peaks':'Peak detection + PCHIP',
    'envelope_sliding':'Sliding maximum / minimum','replicate':'Replicate measurements','replicates':'Replicate measurements'}


def parameter_name(name,preset=None):
    match=re.fullmatch(r'p(\d+)_(.+)',name)
    prefix='Peak '+match[1]+' · ' if match else ''
    key=match[2] if match else name
    if key=='amplitude' and preset and ('gaussian' in preset or 'lorentzian' in preset):
        return prefix+'Area'
    return prefix+PARAMETERS.get(key,key)


def model_name(record):
    key=record['settings']['preset'] or ''
    names={'linear':'Linear','quadratic':'Quadratic','gaussian':'Gaussian','lorentzian':'Lorentzian',
        'double_gaussian':'Double Gaussian','double_lorentzian':'Double Lorentzian','sine':'Sine',
        'damped_sine':'Damped sine','exponential':'Exponential decay','trend_power':'Power law',
        'trend_log':'Logarithmic','trend_exp':'Exponential','trend_piece2':'Two-segment linear',
        'trend_piece3':'Three-segment linear'}
    if key in names:return names[key]
    for prefix,label in [('multi_gaussian_','Gaussian'),('multi_lorentzian_','Lorentzian')]:
        if key.startswith(prefix):return key[len(prefix):]+'-peak '+label
    if key.startswith('polynomial_'):return 'Polynomial (degree '+key.split('_')[-1]+')'
    if not key:return 'Custom formula'
    return record.get('title_en',record['title'])


def fit_rows_english(rows,record):
    cfg=record['settings'];weighted=bool(cfg['columns'][3])
    labels={'model':'Model','equation':'Equation','source':'Source','range':'Fit range','status':'Status',
        'created':'Completed','n':'Number of points','r2':'R²','adjusted_r2':'Adjusted R²','rmse':'RMSE',
        'sse':'Residual sum of squares','nvarys':'Free parameters','weight':'Weighting',
        'dof':'Degrees of freedom','redchi':'Reduced χ²' if weighted else 'Residual variance',
        'evaluations':'Evaluations','message':'Convergence message'}
    result=[]
    for key,label,value,selected in rows:
        if key.startswith(('parameter:','feature:')):
            label=parameter_name(key.split(':',1)[1],cfg['preset'])
            value=value.replace('（固定）',' (fixed)')
        else:
            label=labels.get(key,label)
        if key=='model':value=model_name(record)
        elif key=='range' and not cfg['use_domain']:value='All valid data'
        elif key=='status':value='Stale — refit required' if record['stale'] else 'Fit completed'
        elif key=='weight':value='Y-error weighted' if weighted else 'Unweighted'
        result.append((key,label,value,selected))
    return result


def options_english(options,owner=None):
    from tailor.column_analysis import STATISTICS as names
    labels={'statistics':'Statistics','ddof':'Standard deviation','missing':'Missing values','sampling':'Sampling',
        'points':'Points','step':'Step','interpolation':'Interpolation','reference':'Reference column',
        'reference_value':'Reference value','align':'Alignment','window':'Window points','polyorder':'Polynomial order',
        'edge':'Edge handling','value':'Value','fft_window':'FFT window','detrend':'Detrending',
        'cutoff':'Cutoff frequency','cutoff2':'Upper cutoff','order':'Filter order','envelope_output':'Envelope output',
        'endpoints':'Endpoints','smooth':'Smoothing window','show_marks':'Peak markers','prominence':'Prominence',
        'distance':'Minimum peak distance','replicate_error':'Error type','minimum_count':'Minimum repetitions',
        'region_low':'Region start','region_high':'Region end','region_baseline':'Area baseline'}
    enums={'ddof':{0:'Population (n)',1:'Sample (n−1)'},'missing':{'omit':'Ignore and report','raise':'Stop on missing','reject':'Stop on missing'},
        'sampling':{'points':'Point count','step':'Step'},'interpolation':{'linear':'Linear','pchip':'PCHIP','cubic':'Cubic spline'},
        'fft_window':{'none':'Rectangular','boxcar':'Rectangular','hann':'Hann','hamming':'Hamming','blackman':'Blackman'},
        'detrend':{'none':'None','constant':'Constant','linear':'Linear'},
        'edge':{'auto':'Automatic','interp':'Interpolation','reflect':'Reflection','nearest':'Nearest'},
        'endpoints':{'none':'None','include':'Include endpoints','observed':'Observed endpoints','hold':'Hold nearest peak'},
        'region_baseline':{'zero':'Zero baseline','endpoints':'Endpoint line'},
        'envelope_output':{'both':'Upper and lower','upper':'Upper','lower':'Lower'}}
    parts=[]
    for key,value in options.items():
        if key=='statistics':value=', '.join(STATISTICS.get(names.get(k,k),names.get(k,k)) for k in value)
        elif key=='reference' and value and owner is not None:
            from tailor.column_titles import display
            sheet=next((s for s in owner.get_data_sheets() if s.id==value[0]),None)
            value=display(sheet.model,value[1]) if sheet and value[1] in sheet.model.columnLabels() else str(value)
        elif isinstance(value,bool):value='On' if value else 'Off'
        elif key in enums and isinstance(value,(str,int)):value=enums[key].get(value,value)
        parts.append(labels.get(key,key)+': '+('—' if value is None else str(value)))
    return '; '.join(parts)


def processing_rows_english(rows,tab):
    from tailor.column_titles import letters
    recipe=tab.record['recipe']
    labels={'处理类型':'Operation','方法':'Method','来源':'Source','参数':'Parameters','处理范围':'Range','状态':'Status'}
    columns={}
    for sheet,key,slot,*_ in tab.record['outputs']:
        source=json.loads(sheet.model._metadata.get(key,{}).get('source') or '{}')
        columns[key]=(letters(list(sheet.model.columnLabels()).index(key)),slot.split(':',2)[-1],source.get('counts',{}))
    result=[]
    for key,label,value,on in rows:
        if key.startswith('context:'):
            original=key.split(':',1)[1];label=labels.get(original,label)
            if original=='处理类型':value=CATEGORIES.get(recipe['title'],recipe['title'])
            elif original=='方法':value=METHODS.get(recipe['method'],recipe['method'])
            elif original=='参数':value=options_english(recipe['options'],getattr(tab,'owner',None)) or '—'
            elif original=='处理范围':value=value.replace('全部数据','All data').replace('X范围','X range').replace('所选行','Selected rows')
            elif original=='状态':value='Stale — source or output changed' if value.startswith('已过期') else 'Up to date'
        elif key.startswith('output:'):
            column,metric,_=columns[key.split(':',1)[1]]
            label=(STATISTICS.get(metric,metric)+' ('+column+')') if on else 'Output column'
            if on:
                value=re.sub(r' (个|次)$','',value)
        elif key.startswith('counts:'):
            column,_,counts=columns[key.split(':',1)[1]]
            label='Data counts ('+column+')'
            value='; '.join(name+' '+str(counts.get(k,'—')) for k,name in [('valid','Valid'),('missing','Missing'),('excluded','Excluded')])
        result.append((key,label,value,on))
    return result


def section_language(panel,english,language):
    for record in panel.sections:
        title=record[1].property('sectionTitle')
        record[1].setProperty('sectionCaption',english.get(title,title) if language=='en' else None)
        panel.set_open(record,record[2])
