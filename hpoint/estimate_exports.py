"""Private estimate documents, built entirely from authorised server snapshots.

Client documents never receive cost or profit fields. No external URLs, fonts or
images are fetched. Workbook formulas have cached server-calculated values and
all user text is explicitly written as text, never as a formula or hyperlink.
"""
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path
import threading
import math
import unicodedata

KINDS={"work":"Работы","material":"Материалы","other":"Прочее"}
STATUSES={"draft":"Черновик","approved":"Согласована","completed":"Выполнена","cancelled":"Отменена"}
_font_lock=threading.Lock()
_pdf_lock=threading.Lock()
FONT="HPointManrope"


def _document_text(document):
    """Single-line form fields may contain pasted newlines in historical rows."""
    def clean(value,multiline=False):
        value="".join(char if (ord(char)>=32 and unicodedata.category(char)!="Cs") or char in "\n\t" else " " for char in str(value or ""))
        return value if multiline else " ".join(value.split())
    result=dict(document)
    for key in ("title","organization_title","organization_contact","client_name","object_title","object_address","number"):
        result[key]=clean(result.get(key))
    result["notes"]=clean(result.get("notes"),True)
    result["items"]=[{**item,"title":clean(item["title"]),"unit":clean(item["unit"])} for item in document["items"]]
    return result


def _number(value):
    return format(Decimal(str(value)),",.2f").replace(","," ").replace(".",",")


def _date(value):
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).strftime("%d.%m.%Y")
    except ValueError:return ""


def _register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    with _font_lock:
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT,str(Path(__file__).resolve().parent.parent/"assets"/"manrope-variable.ttf")))


def pdf(document):
    # ReportLab explicitly forbids sharing one dynamic TTFont between documents
    # built simultaneously. Keep its embedded glyph subsets document-local.
    with _pdf_lock:
        return _pdf(_document_text(document))


def _pdf(document):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,Table,TableStyle,KeepTogether
    _register_font()
    buffer=BytesIO();width=A4[0]-72
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=36,leftMargin=36,topMargin=48,bottomMargin=42,
                          title="Смета: "+document["title"],author=document["organization_title"],pageCompression=1)
    ink=colors.HexColor("#20362E");muted=colors.HexColor("#536B61");pale=colors.HexColor("#EDF4F0");line=colors.HexColor("#D5E0DA")
    body=ParagraphStyle("body",fontName=FONT,fontSize=9,leading=13,textColor=ink,spaceAfter=6,splitLongWords=1)
    small=ParagraphStyle("small",parent=body,fontSize=8,leading=11,textColor=muted)
    title=ParagraphStyle("title",parent=body,fontSize=23,leading=29,spaceAfter=12)
    head=ParagraphStyle("head",parent=body,fontSize=10,leading=14,spaceBefore=12,spaceAfter=8)
    right=ParagraphStyle("right",parent=body,fontSize=8,leading=11,alignment=TA_RIGHT,spaceAfter=0)
    cell=ParagraphStyle("cell",parent=body,fontSize=8,leading=11,spaceAfter=0)
    def p(value,style=body):return Paragraph(escape(str(value or "")).replace("\n","<br/>"),style)
    story=[p(document["organization_title"],small),p(document["title"],title)]
    number=document.get("number") or "СМ-"+str(document["id"]).zfill(4)
    metadata=["Смета "+number,STATUSES.get(document.get("status"),"Черновик")]
    issued=_date(document.get("issued_on") or document.get("created_at"))
    if issued:metadata.append("от "+issued)
    story.append(p(" · ".join(metadata),small))
    for label,key in (("Клиент","client_name"),("Объект","object_title"),("Адрес объекта","object_address"),("Контакт исполнителя","organization_contact")):
        if document.get(key):story.append(p(label+": "+document[key]))
    if document.get("valid_until"):story.append(p("Предложение действительно до "+_date(document["valid_until"]),small))
    if document["audience"]=="internal":story.append(p("Внутренний расчёт организации",head))
    story.append(Spacer(1,10))
    headers=["№","Позиция","Раздел","Ед.","Кол-во","Цена, тест. ₽","Сумма, тест. ₽"]
    rows=[[p(value,cell) for value in headers]]
    for index,item in enumerate(document["items"],1):
        rows.append([p(index,cell),p(item["title"],cell),p(KINDS.get(item.get("kind"),"Работы"),cell),p(item["unit"],cell),
                     p(item["quantity"],right),p(_number(item["price_rub"]),right),p(_number(item["total_rub"]),right)])
    table=LongTable(rows,colWidths=[20,166,44,27,57,101,108],repeatRows=1,hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),pale),("TEXTCOLOR",(0,0),(-1,-1),ink),
        ("FONTNAME",(0,0),(-1,-1),FONT),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5),
        ("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LINEBELOW",(0,0),(-1,0),.7,line),("LINEBELOW",(0,1),(-1,-1),.35,line),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F8FAF9")])]))
    story.append(table);story.append(Spacer(1,16))
    totals=[("Стоимость позиций",document["subtotal_rub"])]
    if Decimal(document.get("markup_percent","0")):
        totals.append(("Наценка "+str(document["markup_percent"])+"%",document["markup_rub"]))
    if Decimal(document.get("discount_percent","0")):
        totals.append(("Скидка "+str(document["discount_percent"])+"%","-"+document["discount_rub"]))
    totals.append(("Итого, тест. ₽",document["total_rub"]))
    if document["audience"]=="internal":totals.extend([("Себестоимость, тест. ₽",document["cost_rub"]),("Плановая прибыль, тест. ₽",document["profit_rub"])])
    total_table=Table([[p(label),p(_number(amount),right)] for label,amount in totals],colWidths=[width-130,130],hAlign="LEFT")
    total_table.setStyle(TableStyle([("BACKGROUND",(0,len(totals)-1),(-1,len(totals)-1),pale),("VALIGN",(0,0),(-1,-1),"TOP"),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LINEABOVE",(0,0),(-1,0),.7,line)]))
    story.append(KeepTogether([total_table]))
    if document["audience"]=="internal":
        story.append(p("Себестоимость по позициям",head))
        cost_rows=[[p(x,cell) for x in ("Позиция","За единицу, тест. ₽","Всего, тест. ₽")]]
        cost_rows.extend([[p(item["title"],cell),p(_number(item["cost_rub"]),right),p(_number(item["cost_total_rub"]),right)] for item in document["items"]])
        cost_table=LongTable(cost_rows,colWidths=[width-230,115,115],repeatRows=1,hAlign="LEFT")
        cost_table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("BACKGROUND",(0,0),(-1,0),pale),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LINEBELOW",(0,0),(-1,-1),.35,line)]))
        story.append(cost_table)
    if document.get("notes"):story.extend([p("Примечания",head),p(document["notes"])])
    story.extend([Spacer(1,14),p("Расчёт в тестовых рублях H-Point. Документ не создаёт платёж и не списывает средства.",small)])
    def page_frame(canvas,document_page):
        canvas.saveState();canvas.setFont(FONT,8);canvas.setFillColor(muted)
        canvas.drawString(36,A4[1]-29,"H-Point · "+("Внутренний расчёт" if document["audience"]=="internal" else "Смета"))
        canvas.drawRightString(A4[0]-36,23,"Страница "+str(document_page.page))
        canvas.restoreState()
    doc.build(story,onFirstPage=page_frame,onLaterPages=page_frame)
    return buffer.getvalue()


def xlsx(document):
    import xlsxwriter
    document=_document_text(document)
    buffer=BytesIO()
    workbook=xlsxwriter.Workbook(buffer,{"in_memory":True,"strings_to_formulas":False,"strings_to_urls":False})
    workbook.set_properties({"title":"Смета: "+document["title"],"author":document["organization_title"],"company":"H-Point"})
    workbook.set_calc_mode("auto")
    common={"font_name":"Manrope","font_size":10,"font_color":"#20362E","valign":"vcenter"}
    def fmt(**values):return workbook.add_format({**common,**values})
    styles={"title":fmt(font_size=21,bold=True,text_wrap=True),"org":fmt(font_size=11,bold=True,text_wrap=True),"text":fmt(text_wrap=True),
            "muted":fmt(font_color="#536B61",font_size=9,text_wrap=True),"header":fmt(bg_color="#DCEBE2",bold=True,text_wrap=True,bottom=1,bottom_color="#9BB5A6"),
            "money":fmt(num_format='#,##0.00',align="right"),"quantity":fmt(num_format='#,##0.####',align="right"),
            "percent":fmt(num_format='0.####%',align="right"),"label":fmt(bold=True),"total":fmt(bold=True,bg_color="#DCEBE2",num_format='#,##0.00',top=1,top_color="#9BB5A6"),
            "date":fmt(num_format="dd.mm.yyyy"),"input_money":fmt(num_format='#,##0.00',font_color="#1750A0",align="right"),"input_number":fmt(num_format='#,##0.####',font_color="#1750A0",align="right")}
    def number(sheet,row,col,value,style="money"):
        sheet.write_number(row,col,float(Decimal(str(value))),styles[style])
    def text(sheet,row,col,value,style="text"):
        sheet.write_string(row,col,str(value or ""),styles[style])
    def formula(sheet,row,col,value,cached,style="money"):
        sheet.write_formula(row,col,value,styles[style],float(Decimal(str(cached))))
    def setup(sheet,widths):
        sheet.hide_gridlines(2);sheet.set_zoom(95);sheet.freeze_panes(9,2);sheet.set_paper(9);sheet.fit_to_pages(1,0)
        sheet.set_margins(.35,.35,.4,.4);sheet.repeat_rows(8);sheet.set_footer("&LH-Point&CСмета&RСтраница &P из &N")
        for column,width in enumerate(widths):sheet.set_column(column,column,width)
    sheet=workbook.add_worksheet("Смета");setup(sheet,[5,42,16,9,14,18,21])
    sheet.merge_range(0,0,0,6,document["organization_title"],styles["org"]);sheet.set_row(0,max(23,math.ceil(len(document["organization_title"])/100)*15))
    title_height=max(48,math.ceil(len(document["title"])/60)*29)
    sheet.merge_range(1,0,2,6,document["title"],styles["title"]);sheet.set_row(1,title_height/2);sheet.set_row(2,title_height/2)
    if document.get("organization_contact"):
        sheet.merge_range(3,0,3,6,document["organization_contact"],styles["muted"]);sheet.set_row(3,max(18,math.ceil(len(document["organization_contact"])/110)*13))
    estimate_number=document.get("number") or "СМ-"+str(document["id"]).zfill(4)
    sheet.merge_range(4,0,4,1,"Смета №",styles["label"]);sheet.merge_range(4,2,4,3,estimate_number,styles["text"]);sheet.set_row(4,max(24,math.ceil(len(estimate_number)/20)*15))
    text(sheet,4,4,"Дата","label")
    date_value=document.get("issued_on") or str(document.get("created_at","")).split("T")[0].split(" ")[0]
    sheet.merge_range(4,5,4,6,"",styles["date"])
    try:sheet.write_datetime(4,5,datetime.strptime(date_value,"%Y-%m-%d"),styles["date"])
    except ValueError:text(sheet,4,5,date_value)
    client=document.get("client_name") or "Не указан"
    sheet.merge_range(5,0,5,1,"Клиент",styles["label"]);sheet.merge_range(5,2,5,6,client,styles["text"]);sheet.set_row(5,max(24,math.ceil(len(client)/65)*15))
    object_text=" · ".join(filter(None,[document.get("object_title"),document.get("object_address")]))
    sheet.merge_range(6,0,6,1,"Объект",styles["label"]);sheet.merge_range(6,2,6,6,object_text,styles["text"]);sheet.set_row(6,max(24,math.ceil(len(object_text)/65)*15))
    sheet.merge_range(7,0,7,3,"Статус: "+STATUSES.get(document.get("status"),"Черновик"),styles["muted"])
    if document.get("valid_until"):
        text(sheet,7,4,"Срок до","muted");sheet.merge_range(7,5,7,6,"",styles["date"])
        sheet.write_datetime(7,5,datetime.strptime(document["valid_until"],"%Y-%m-%d"),styles["date"])
    headers=["№","Позиция","Раздел","Ед.","Количество","Цена, тест. ₽","Сумма, тест. ₽"]
    for col,value in enumerate(headers):text(sheet,8,col,value,"header")
    sheet.set_row(8,32)
    for index,item in enumerate(document["items"]):
        row=9+index;sheet.set_row(row,max(24,math.ceil(len(item["title"])/36)*15,math.ceil(len(item["unit"])/7)*15))
        sheet.write_number(row,0,index+1,styles["quantity"]);text(sheet,row,1,item["title"]);text(sheet,row,2,KINDS.get(item.get("kind"),"Работы"));text(sheet,row,3,item["unit"])
        number(sheet,row,4,item["quantity"],"input_number");number(sheet,row,5,item["price_rub"],"input_money")
        formula(sheet,row,6,f"=ROUND(E{row+1}*F{row+1},2)",item["total_rub"])
    last=9+len(document["items"])-1;summary=last+2
    sheet.autofilter(8,0,last,6)
    sheet.data_validation(9,4,last,4,{"validate":"decimal","criteria":">","value":0,"input_title":"Количество","input_message":"Положительное число, до 4 знаков после запятой."})
    sheet.data_validation(9,5,last,5,{"validate":"decimal","criteria":">=","value":0})
    summaries=[("Стоимость позиций",document["subtotal_rub"]),("Наценка, %",Decimal(document["markup_percent"])/100),("Сумма наценки",document["markup_rub"]),
               ("Скидка, %",Decimal(document.get("discount_percent","0"))/100),("Сумма скидки",document["discount_rub"]),("Итого, тест. ₽",document["total_rub"])]
    for offset,(label,value) in enumerate(summaries):
        sheet.merge_range(summary+offset,1,summary+offset,5,label,styles["label"]);sheet.set_row(summary+offset,25)
    formula(sheet,summary,6,f"=SUM(G10:G{last+1})",document["subtotal_rub"])
    number(sheet,summary+1,6,Decimal(document["markup_percent"])/100,"percent")
    formula(sheet,summary+2,6,f"=ROUND(G{summary+1}*G{summary+2},2)",document["markup_rub"])
    number(sheet,summary+3,6,Decimal(document.get("discount_percent","0"))/100,"percent")
    formula(sheet,summary+4,6,f"=ROUND((G{summary+1}+G{summary+3})*G{summary+4},2)",document["discount_rub"])
    formula(sheet,summary+5,6,f"=G{summary+1}+G{summary+3}-G{summary+5}",document["total_rub"],"total")
    sheet.data_validation(summary+1,6,summary+1,6,{"validate":"decimal","criteria":"between","minimum":0,"maximum":10})
    sheet.data_validation(summary+3,6,summary+3,6,{"validate":"decimal","criteria":"between","minimum":0,"maximum":1})
    end=summary+7
    if document.get("notes"):
        sheet.merge_range(end,0,end,6,"Примечания",styles["label"]);end+=1
        for paragraph in document["notes"].splitlines() or [document["notes"]]:
            for offset in range(0,max(1,len(paragraph)),1000):
                fragment=paragraph[offset:offset+1000]
                sheet.merge_range(end,0,end,6,fragment,styles["text"]);sheet.set_row(end,max(22,15*math.ceil(len(fragment)/110)));end+=1
    sheet.merge_range(end+1,0,end+1,6,"Тестовые рубли H-Point. Смета не создаёт платёж и не списывает средства.",styles["muted"])
    sheet.set_row(end+1,30);sheet.print_area(0,0,end+1,6)
    if document["audience"]=="internal":
        internal=workbook.add_worksheet("Внутренний расчёт");setup(internal,[5,42,14,18,20,20,20])
        internal_title="Внутренний расчёт · "+document["title"]
        internal.merge_range(0,0,1,6,internal_title,styles["title"])
        internal_height=max(48,math.ceil(len(internal_title)/60)*29)
        internal.set_row(0,internal_height/2);internal.set_row(1,internal_height/2)
        internal.merge_range(2,0,2,6,"Себестоимость и плановая прибыль. Для команды руководителей.",styles["muted"])
        for col,value in enumerate(["№","Позиция","Количество","Цена продажи","Себестоимость / ед.","Себестоимость всего","Стоимость позиций"]):text(internal,8,col,value,"header")
        internal.set_row(8,34)
        for index,item in enumerate(document["items"]):
            row=9+index;internal.set_row(row,max(24,math.ceil(len(item["title"])/36)*15))
            internal.write_number(row,0,index+1,styles["quantity"]);text(internal,row,1,item["title"])
            formula(internal,row,2,f"='Смета'!E{row+1}",item["quantity"],"quantity")
            formula(internal,row,3,f"='Смета'!F{row+1}",item["price_rub"])
            number(internal,row,4,item["cost_rub"],"input_money")
            formula(internal,row,5,f"=ROUND(C{row+1}*E{row+1},2)",item["cost_total_rub"]);formula(internal,row,6,f"=ROUND(C{row+1}*D{row+1},2)",item["total_rub"])
        internal.autofilter(8,0,last,6)
        for offset,(label,value) in enumerate((("Итого для клиента",document["total_rub"]),("Себестоимость",document["cost_rub"]),("Плановая прибыль",document["profit_rub"]))):
            internal.merge_range(summary+offset,1,summary+offset,5,label,styles["label"])
        formula(internal,summary,6,f"='Смета'!G{summary+6}",document["total_rub"])
        formula(internal,summary+1,6,f"=SUM(F10:F{last+1})",document["cost_rub"])
        formula(internal,summary+2,6,f"=G{summary+1}-G{summary+2}",document["profit_rub"],"total")
        internal.print_area(0,0,summary+2,6)
    workbook.close()
    return buffer.getvalue()
