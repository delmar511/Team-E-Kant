from kiwipiepy import Kiwi
import re

k = Kiwi()

VISA_CODE = r"[A-Za-z]-\d+(?:-\d+)?"
KEEP = ("NN","VV","VA","SL","SN")

def tokenize(text, protect=True):
    """BM25 입력 토큰 목록을 돌려준다.

    protect=False 로 두면 보호 규칙 없이 동작한다. 비교 실험용.
    """
    codes = []
    if protect:
         codes = [ c.upper() for c in re.findall(VISA_CODE, text)]
         text = re.sub(VISA_CODE," ",text)
    return codes + [t.form for t in k.tokenize(text) if t.tag.startswith(KEEP)]

if __name__ == "__main__":
      print(tokenize("E-7 비자를 연장하려면", protect=True))
      print(tokenize("특정활동(E-7) 자격을 가진 사람"))
      print(tokenize("D-2-2 학사과정과 D-4-1 어학연수"))
      print(tokenize("어학당 다니는데 알바하려면 뭐가 필요해?"))
      print(tokenize("e-7 비자 연장"))
