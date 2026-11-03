"""Display-only dimensional metadata for existing algorithms; no unit conversion."""
import re


def grouped(unit):
    return f'({unit})' if any(c in unit for c in '/·* ') and not unit.startswith('(') else unit


def squared(unit):
    return grouped(unit)+'²' if unit else ''


def product(a,b):
    return f'{grouped(a)}·{grouped(b)}' if a and b else ''


def quotient(a,b):
    return ('1' if a==b else f'{grouped(a)}/{grouped(b)}') if a and b else ''


def reciprocal(unit):
    return f'1/{grouped(unit)}' if unit else ''


def parameter_unit(preset,name,units):
    """Only built-in model dimensions are known; custom coefficients stay unknown."""
    if not preset:return ''
    x,y=units.get('x',''),units.get('y','')
    name=re.sub(r'^p\d+_','',name)
    if name in {'center','sigma','decay','origin','breakpoint','breakpoint2','fwhm','period','shift'}:
        if name=='shift' and preset in {'sine','damped_sine'}:return 'rad'
        return x
    if name in {'offset','intercept','height','c'}:return y
    if name in {'slope','delta','delta2','b'}:return quotient(y,x)
    if name=='a':return quotient(y,squared(x)) if x else ''
    if re.fullmatch(r'c\d+',name):
        degree=int(name[1:]);return y if degree==0 else quotient(y,x if degree==1 else f'{grouped(x)}^{degree}')
    if name in {'area','amplitude'}:
        if 'gaussian' in preset or 'lorentzian' in preset:return product(x,y)
        if preset=='trend_power':return f'{y}/({x}^exponent)' if x and y else ''
        return y
    if name=='frequency':return f'rad/{x}' if x else ''
    if name in {'rate','frequency_cycles'}:return reciprocal(x)
    if name=='exponent':return '1'
    return ''


def processing_unit(method,slot,units,reference_unit=None):
    x,y=units.get('x',''),units.get('y','')
    if slot=='X':return reciprocal(x) if method.startswith('fft_') else x
    if slot in {'起点X','终点X','最小值X','最大值X'}:return x
    if slot=='有效点数':return '个'
    if slot=='有效次数N':return '次'
    if slot=='R²':return '1'
    if slot in {'斜率','斜率标准误'} or method=='derivative':return quotient(y,x)
    if slot=='积分' or method=='cumulative':return product(x,y)
    if method in {'normalize_max','normalize_range'}:return '1'
    if method=='fft_power':return product(squared(y),x) if y and x else ''
    if method=='multiply' and reference_unit is not None:return product(y,reference_unit)
    if method=='divide' and reference_unit is not None:return quotient(y,reference_unit)
    return y
