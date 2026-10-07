"""Read HTML tables while retaining their original table and row positions."""
from html.parser import HTMLParser

class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.tables=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table':
            if self.table is not None:raise ValueError('Nested table requires review')
            self.table=[]
        elif tag=='tr' and self.table is not None:self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
        elif tag in ('br','p') and self.cell is not None:self.cell.append(' ')
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row is not None:self.table.append(self.row);self.row=None
        elif tag=='table' and self.table is not None:self.tables.append(self.table);self.table=None

def tables(text):
    parser=TableReader();parser.feed(text);parser.close();return parser.tables
