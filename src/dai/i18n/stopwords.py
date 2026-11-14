"""Stop words, negation cues and abbreviations (English + Turkish).

Word lists are *raw*; use tokenize.fold() before comparing.
"""

EN_STOP = """a an the and or but if of to in on for with at by from as is are was were be been
being am it its this that these those there here he she they we you i his her their our your my
me him them us has have had do does did will would can could may might shall should also than
then so such very more most other into about over under after before between through during up
down out off again further once each both few some any own same too just only said says say
according per via which who whom whose what when where why how all while until against among
within without upon since because""".split()

TR_STOP = """ve ile bir bu şu o da de ki mi mı mu mü için gibi daha çok en ama fakat ancak veya ya
hem ise olan olarak olup oldu olduğu olduğunu bunu buna bunun bunlar şunu onu ona onun onlar her
bütün tüm kadar sonra önce göre ayrıca yine hala henüz çünkü eğer ben sen biz siz ne nasıl neden
hangi kendi dedi diyor açıkladı belirtti söyledi kaç nedir kimdir nerede ne zaman kim niçin
olarak üzere ise bunun şöyle böyle zaten ayrıca sadece yalnızca""".split()

NEG_EN = {"not", "no", "never", "none", "neither", "nor", "cannot", "without", "denied",
          "denies", "deny", "false", "untrue", "refuted"}
NEG_TR = {"değil", "yok", "hayır", "asla", "hiç", "hiçbir", "yalanladı", "yalanlıyor",
          "reddetti", "reddediyor"}
# Turkish negation is a verb suffix (-ma/-me); words that merely end like it:
TR_NEG_EXCEPTIONS = {"komedi", "tragikomedi", "medi", "kadi", "radyo"}

ABBR = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "inc", "ltd", "co",
        "corp", "no", "approx", "dept", "est", "fig", "al", "jan", "feb", "mar", "apr", "jun",
        "jul", "aug", "sep", "sept", "oct", "nov", "dec", "sn", "doç", "yrd", "av", "vb",
        "bkz", "örn", "yy", "sh", "sf", "tel", "şti", "a.ş", "u.s", "e.g", "i.e", "u.k"}
