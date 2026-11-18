//! 第二階段：會合評估、避碰決策與 RPO 控制模擬（Sprint 0 規格與測試骨架＋Sprint 1 自適應搜尋、協方差傳播、批次＋Sprint 2 避碰決策＋Sprint 3 RPO 控制模擬）。
//!
//! Python `scenario-advanced01/scenario04/phase2/` 的同演算法移植；兩邊以 `config/phase2/testdata/`
//! （由 scripts/sync_web.py 自 Python 版同步）共用測試資料比對。模組對應關係與 Python 相同。
#![allow(dead_code)]

pub mod batch;
pub mod constants;
pub mod covprop;
pub mod csvio;
pub mod e2e;
pub mod eop;
pub mod ephemeris;
pub mod events;
pub mod forces;
pub mod frames;
pub mod integrator;
pub mod kepler;
pub mod maneuver;
pub mod pc;
pub mod rpo;
pub mod rtn;
pub mod schema;
pub mod screening;
pub mod tca;
pub mod timescale;
#[cfg(test)]
mod tests;
#[cfg(test)]
mod tests_sprint1;
#[cfg(test)]
mod tests_sprint2;
#[cfg(test)]
mod tests_sprint3;

pub type V3 = [f64; 3];
pub type M3 = [[f64; 3]; 3];

pub mod la {
    use super::{M3, V3};

    pub fn add(a: V3, b: V3) -> V3 {
        [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
    }
    pub fn sub(a: V3, b: V3) -> V3 {
        [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    }
    pub fn scale(a: V3, s: f64) -> V3 {
        [a[0] * s, a[1] * s, a[2] * s]
    }
    pub fn dot(a: V3, b: V3) -> f64 {
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    }
    pub fn norm(a: V3) -> f64 {
        dot(a, a).sqrt()
    }
    pub fn cross(a: V3, b: V3) -> V3 {
        [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    }
    pub fn mv(m: &M3, v: V3) -> V3 {
        [dot(m[0], v), dot(m[1], v), dot(m[2], v)]
    }
    pub fn mtv(m: &M3, v: V3) -> V3 {
        [
            m[0][0] * v[0] + m[1][0] * v[1] + m[2][0] * v[2],
            m[0][1] * v[0] + m[1][1] * v[1] + m[2][1] * v[2],
            m[0][2] * v[0] + m[1][2] * v[1] + m[2][2] * v[2],
        ]
    }
    pub fn mm(a: &M3, b: &M3) -> M3 {
        let mut c = [[0.0; 3]; 3];
        for i in 0..3 {
            for j in 0..3 {
                c[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
            }
        }
        c
    }
    pub fn transpose(a: &M3) -> M3 {
        let mut t = [[0.0; 3]; 3];
        for i in 0..3 {
            for j in 0..3 {
                t[i][j] = a[j][i];
            }
        }
        t
    }
    /// 一般 n×n（列優先 Vec<Vec>）乘法與轉置，供 6×6 協方差使用
    pub fn matmul(a: &[Vec<f64>], b: &[Vec<f64>]) -> Vec<Vec<f64>> {
        let (n, m, p) = (a.len(), b.len(), b[0].len());
        let mut c = vec![vec![0.0; p]; n];
        for i in 0..n {
            for k in 0..m {
                let aik = a[i][k];
                for j in 0..p {
                    c[i][j] += aik * b[k][j];
                }
            }
        }
        c
    }
    pub fn mat_t(a: &[Vec<f64>]) -> Vec<Vec<f64>> {
        let (n, m) = (a.len(), a[0].len());
        (0..m).map(|j| (0..n).map(|i| a[i][j]).collect()).collect()
    }
    /// Cholesky 分解成功即正定
    pub fn is_pd(a: &[Vec<f64>]) -> bool {
        let n = a.len();
        let mut l = vec![vec![0.0; n]; n];
        for i in 0..n {
            for j in 0..=i {
                let mut s = a[i][j];
                for k in 0..j {
                    s -= l[i][k] * l[j][k];
                }
                if i == j {
                    if !(s > 0.0) {
                        return false;
                    }
                    l[i][i] = s.sqrt();
                } else {
                    l[i][j] = s / l[j][j];
                }
            }
        }
        true
    }
    pub fn inv(a: &[Vec<f64>]) -> Option<Vec<Vec<f64>>> {
        let n = a.len();
        let mut m: Vec<Vec<f64>> = a.iter().cloned().collect();
        let mut r: Vec<Vec<f64>> = (0..n).map(|i| (0..n).map(|j| if i == j { 1.0 } else { 0.0 }).collect()).collect();
        for c in 0..n {
            let p = (c..n).max_by(|&x, &y| m[x][c].abs().total_cmp(&m[y][c].abs()))?;
            if m[p][c].abs() < 1e-300 {
                return None;
            }
            m.swap(c, p);
            r.swap(c, p);
            let d = m[c][c];
            for j in 0..n {
                m[c][j] /= d;
                r[c][j] /= d;
            }
            for i in 0..n {
                if i != c {
                    let f = m[i][c];
                    if f != 0.0 {
                        for j in 0..n {
                            m[i][j] -= f * m[c][j];
                            r[i][j] -= f * r[c][j];
                        }
                    }
                }
            }
        }
        Some(r)
    }
}

/// schema_cases／maneuver_cases 的 ops（同 Python api/lab.apply_ops）：set 設值、del 刪除；path 為鍵或索引
pub fn apply_ops(base: &serde_json::Value, ops: &serde_json::Value) -> serde_json::Value {
    use serde_json::Value;
    let mut d = base.clone();
    for op in ops.as_array().map(Vec::as_slice).unwrap_or(&[]) {
        let path = op["path"].as_array().unwrap();
        let (head, last) = path.split_at(path.len() - 1);
        let mut tgt = &mut d;
        for k in head {
            tgt = match k {
                Value::String(s) => tgt.get_mut(s.as_str()).unwrap(),
                Value::Number(n) => tgt.get_mut(n.as_u64().unwrap() as usize).unwrap(),
                _ => unreachable!(),
            };
        }
        let set = op["op"] == "set";
        match &last[0] {
            Value::String(s) => {
                let m = tgt.as_object_mut().unwrap();
                if set {
                    m.insert(s.clone(), op["value"].clone());
                } else {
                    m.remove(s);
                }
            }
            Value::Number(n) => {
                let a = tgt.as_array_mut().unwrap();
                let i = n.as_u64().unwrap() as usize;
                if set {
                    a[i] = op["value"].clone();
                } else {
                    a.remove(i);
                }
            }
            _ => unreachable!(),
        }
    }
    d
}
