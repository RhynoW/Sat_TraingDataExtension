//! 極簡正則（不分大小寫、`re.search` 語意），只支援故事群組與偵照分類規則用到的語法：
//! 頂層 `|` 分支、`^` 錨點、字面字元、`[...]` 字元集、`(a|b|…)` 群組、`\b` 字邊界、`?` 量詞。
//! 不另引入 regex crate（避免修改 Cargo.toml）；語法超出範圍時 `compile` 回傳錯誤。

#[derive(Debug, Clone)]
enum Atom {
    Lit(char),
    Class(Vec<char>),
    /// 群組：每個分支為一串原子
    Group(Vec<Vec<Piece>>),
    WordBoundary,
}

#[derive(Debug, Clone)]
struct Piece {
    atom: Atom,
    optional: bool,
}

#[derive(Debug, Clone)]
struct Branch {
    anchored: bool,
    seq: Vec<Piece>,
}

#[derive(Debug, Clone)]
pub struct Rx {
    branches: Vec<Branch>,
}

fn up(c: char) -> char {
    let mut u = c.to_uppercase();
    match (u.next(), u.next()) {
        (Some(x), None) => x,
        _ => c,
    }
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

struct Parser<'a> {
    s: &'a [char],
    i: usize,
}

impl Parser<'_> {
    fn peek(&self) -> Option<char> {
        self.s.get(self.i).copied()
    }

    /// 解析一串原子，直到 `|`、`)` 或結尾
    fn seq(&mut self) -> Result<Vec<Piece>, String> {
        let mut out: Vec<Piece> = Vec::new();
        while let Some(c) = self.peek() {
            let atom = match c {
                '|' | ')' => break,
                '\\' => {
                    self.i += 1;
                    match self.peek() {
                        Some('b') => Atom::WordBoundary,
                        Some(x) if !x.is_alphanumeric() => Atom::Lit(x),
                        other => return Err(format!("不支援的跳脫序列 \\{other:?}")),
                    }
                }
                '[' => {
                    self.i += 1;
                    let mut set = Vec::new();
                    loop {
                        match self.peek() {
                            Some(']') => break,
                            Some('\\') => {
                                self.i += 1;
                                set.push(up(self.peek().ok_or("字元集未結束")?));
                            }
                            Some(x) => set.push(up(x)),
                            None => return Err("字元集未結束".into()),
                        }
                        self.i += 1;
                    }
                    Atom::Class(set)
                }
                '(' => {
                    self.i += 1;
                    let mut alts = vec![self.seq()?];
                    while self.peek() == Some('|') {
                        self.i += 1;
                        alts.push(self.seq()?);
                    }
                    if self.peek() != Some(')') {
                        return Err("群組未結束".into());
                    }
                    Atom::Group(alts)
                }
                '?' => {
                    let last = out.last_mut().ok_or("`?` 前無原子")?;
                    last.optional = true;
                    self.i += 1;
                    continue;
                }
                '^' | '$' | '*' | '+' | '.' | '{' => {
                    return Err(format!("不支援的語法 `{c}`（位置 {}）", self.i))
                }
                x => Atom::Lit(up(x)),
            };
            self.i += 1;
            out.push(Piece {
                atom,
                optional: false,
            });
        }
        Ok(out)
    }
}

impl Rx {
    pub fn compile(pat: &str) -> Result<Self, String> {
        let chars: Vec<char> = pat.chars().collect();
        let mut p = Parser { s: &chars, i: 0 };
        let mut branches = Vec::new();
        loop {
            let anchored = p.peek() == Some('^');
            if anchored {
                p.i += 1;
            }
            let seq = p.seq()?;
            branches.push(Branch { anchored, seq });
            match p.peek() {
                Some('|') => p.i += 1,
                None => break,
                Some(c) => return Err(format!("未預期的 `{c}`")),
            }
        }
        Ok(Self { branches })
    }

    /// 不分大小寫之 `search`
    pub fn search(&self, text: &str) -> bool {
        let t: Vec<char> = text.chars().map(up).collect();
        self.branches.iter().any(|b| {
            let last = if b.anchored { 0 } else { t.len() };
            (0..=last).any(|start| match_seq(&b.seq, &t, start, &mut |_| true))
        })
    }
}

/// 回溯比對：seq 自 pos 起比對成功後呼叫 k(結束位置)
fn match_seq(seq: &[Piece], t: &[char], pos: usize, k: &mut dyn FnMut(usize) -> bool) -> bool {
    let Some((first, rest)) = seq.split_first() else {
        return k(pos);
    };
    let mut cont = |p: usize| match_seq(rest, t, p, k);
    let matched = match_atom(&first.atom, t, pos, &mut cont);
    matched || (first.optional && match_seq(rest, t, pos, k))
}

fn match_atom(a: &Atom, t: &[char], pos: usize, k: &mut dyn FnMut(usize) -> bool) -> bool {
    match a {
        Atom::Lit(c) => t.get(pos) == Some(c) && k(pos + 1),
        Atom::Class(set) => t.get(pos).is_some_and(|c| set.contains(c)) && k(pos + 1),
        Atom::WordBoundary => {
            let before = pos > 0 && is_word(t[pos - 1]);
            let after = t.get(pos).is_some_and(|&c| is_word(c));
            before != after && k(pos)
        }
        Atom::Group(alts) => alts.iter().any(|alt| match_seq(alt, t, pos, k)),
    }
}

#[cfg(test)]
mod tests {
    use super::Rx;

    #[test]
    fn basic() {
        let r = Rx::compile(r"^YAOGAN[- ]?(30|20|25|31|39|40)\b").unwrap();
        assert!(r.search("YAOGAN-30 01A"));
        assert!(r.search("yaogan 20"));
        assert!(r.search("YAOGAN31"));
        assert!(!r.search("YAOGAN-301"));
        assert!(!r.search("XYAOGAN-30"));
        let r = Rx::compile(r"JILIN|^JL-?1").unwrap();
        assert!(r.search("CHINA JILIN-1 GF03"));
        assert!(r.search("JL1-GF"));
        assert!(r.search("JL-1"));
        assert!(!r.search("XJL-1"));
        let r = Rx::compile(r"^ZY |^SJ ").unwrap();
        assert!(r.search("ZY 1-02D"));
        assert!(!r.search("ZY-1"));
        let r = Rx::compile(r"^GAOFEN[- ]?11\b").unwrap();
        assert!(r.search("GAOFEN-11 02"));
        assert!(!r.search("GAOFEN-1"));
        assert!(Rx::compile("A.*B").is_err());
    }
}
