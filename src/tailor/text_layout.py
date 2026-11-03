"""Shared Qt text orientation and eligible alphabetic text runs."""
import unicodedata
from PySide6 import QtCore, QtGui

ORIENTATIONS = [('横排','horizontal'),('逆90度','ccw90'),('顺90度','cw90')]


def rotation(spec):
    return {'ccw90':-90., 'cw90':90., 'vertical':-90.}.get(spec.get('text_orientation'),0.)


def alphabetic(char):
    name=unicodedata.name(char,'')
    return (unicodedata.category(char) in {'Lu','Ll','Lt','Lm'} and
            not any(s in name for s in ('IDEOGRAPH','CJK','HIRAGANA','KATAKANA','HANGUL')))


def selected_letters(cursor):
    if not cursor.hasSelection():return []
    start,end=cursor.selectionStart(),cursor.selectionEnd()
    text=cursor.document().toPlainText()
    position=0;result=[]
    for index,char in enumerate(text):
        count=2 if ord(char)>0xffff else 1
        if start<=position and position+count<=end and alphabetic(char):
            cluster=count;tail=index+1
            while tail<len(text) and unicodedata.combining(text[tail]) and position+cluster<end:
                cluster+=2 if ord(text[tail])>0xffff else 1;tail+=1
            result.append((position,cluster,char))
        position+=count
    return result


def format_letters(cursor, operation):
    letters=selected_letters(cursor)
    if not letters:return
    edit=QtGui.QTextCursor(cursor.document());edit.beginEditBlock()
    try:
        for position,count,char in letters:
            edit.setPosition(position);edit.setPosition(position+count,QtGui.QTextCursor.KeepAnchor)
            fmt=QtGui.QTextCharFormat();operation(fmt,edit.charFormat());edit.mergeCharFormat(fmt)
    finally:edit.endEditBlock()


def plain_text(value):
    from tailor.text_accents import restyle
    return QtGui.QTextDocumentFragment.fromHtml(restyle(value,{})).toPlainText()


def mpl_text(value, spec=None):
    """Delegate scientific inline scripts to Matplotlib's existing MathText."""
    from tailor.text_accents import restyle
    doc=QtGui.QTextDocument();doc.setHtml(restyle(value,{}));rows=[];block=doc.begin()
    while block.isValid():
        parts=[];iterator=block.begin()
        while not iterator.atEnd():
            fragment=iterator.fragment();fmt=fragment.charFormat();text=fragment.text()
            alignment=fmt.verticalAlignment()
            def segment(value):
                if not value:return ''
                if alignment in (QtGui.QTextCharFormat.AlignSuperScript,QtGui.QTextCharFormat.AlignSubScript) or fmt.fontOverline():
                    escaped=value.replace('\\',r'\backslash ').replace('{',r'\{').replace('}',r'\}')
                    style=spec or {}
                    bold=fmt.fontWeight()>=QtGui.QFont.Bold if fmt.hasProperty(QtGui.QTextFormat.FontWeight) else style.get('bold',False)
                    italic=fmt.fontItalic() if fmt.hasProperty(QtGui.QTextFormat.FontItalic) else style.get('italic',False)
                    face='mathbfit' if bold and italic else 'mathbf' if bold else 'mathit' if italic else 'mathregular'
                    body='\\'+face+'{'+escaped+'}'
                    if fmt.fontOverline():body=r'\overline{'+body+'}'
                    if alignment==QtGui.QTextCharFormat.AlignSuperScript:body='^{'+body+'}'
                    elif alignment==QtGui.QTextCharFormat.AlignSubScript:body='_{'+body+'}'
                    return '$'+body+'$'
                return value.replace('$',r'\$')
            parts.append('\n'.join(segment(s) for s in text.replace('\u2028','\n').replace('\u2029','\n').split('\n')))
            iterator+=1
        rows.append(''.join(parts));block=block.next()
    return '\n'.join(rows)
