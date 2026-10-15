"""Exercise the EA's date expression against trades at the forward boundary."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import re
import unittest


class ExportBackBoundaryTests(unittest.TestCase):
    def test_verifier_excludes_forward_day_using_the_actual_ea_expression(self):
        text=(Path(__file__).parent.parent/'GOAT V1.49.mq5').read_text(encoding='utf-8-sig')
        marker=text.index('DEINIT: Running top Score Set on back history only')
        match=re.search(r'strT\.toDate=TimeToString\(([^,]+),TIME_DATE\);',text[marker:marker+700])
        self.assertIsNotNone(match)
        boundary=int(datetime(2026,3,26,tzinfo=timezone.utc).timestamp())
        expression=match[1].replace('xmlData.forwardD',str(boundary))
        tree=ast.parse(expression,mode='eval')
        self.assertTrue(all(isinstance(node,(ast.Expression,ast.BinOp,ast.Constant,ast.Add,ast.Mult))
                            for node in ast.walk(tree)))
        end=eval(compile(tree,'<EA date arithmetic>','eval'),{'__builtins__':{}})
        # MT5's ToDate is exclusive. The old +24h included these five forward-day
        # trades, reproducing the native 617 versus 622-trade discrepancy.
        times=[boundary-3600]*617+[boundary+i*3600 for i in range(5)]
        self.assertEqual(sum(t<end for t in times),617)
        self.assertEqual(sum(t<boundary+86400 for t in times),622)
        self.assertEqual(end,boundary)

    def test_same_profit_with_a_different_trade_count_cannot_verify(self):
        text=(Path(__file__).parent.parent/'GOAT V1.49.mq5').read_text(encoding='utf-8-sig')
        start=text.index('if(Init && DoubleToString(profit,0)==DoubleToString(xmlData.Rows[0].back_profit,0)')
        condition=text[start:text.index('{',start)].strip()[3:-1]
        for trades,wanted in ((617,True),(622,False)):
            expression=condition.replace('Init','True').replace('&&',' and ')
            for key,value in {'DoubleToString(profit,0)':1322,
                'DoubleToString(xmlData.Rows[0].back_profit,0)':1322,
                'DoubleToString(trades,0)':trades,
                'DoubleToString(xmlData.Rows[0].back_trades,0)':617}.items():
                expression=expression.replace(key,str(value))
            expression=' '.join(expression.split())
            tree=ast.parse(expression,mode='eval')
            self.assertTrue(all(isinstance(node,(ast.Expression,ast.BoolOp,ast.And,ast.Constant,
                ast.Compare,ast.Eq)) for node in ast.walk(tree)))
            self.assertEqual(eval(compile(tree,'<EA verification predicate>','eval'),
                {'__builtins__':{}}),wanted)


if __name__=='__main__':unittest.main()
