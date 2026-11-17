'use strict';

/* 極簡 GIF89a 編碼器（自適應 256 色全域色盤〔中位切割〕+ LZW），無外部相依。
   用於 /taipei 天球動畫輸出。用法：
     const g = new GifEncoder(w, h, delayCs);   // delayCs：每格延遲（1/100 秒）
     g.buildPalette([rgbaA, rgbaB, ...]);       // 以數張代表影格建立色盤（可省略，改用首格）
     g.addFrame(imageData.data);                // RGBA Uint8ClampedArray
     const blob = g.finish();                   // Blob('image/gif')                  */
(function(){
  class GifEncoder{
    constructor(w, h, delayCs){
      this.w = w; this.h = h; this.delay = Math.max(2, Math.round(delayCs));
      this.parts = []; this.table = new Int32Array(1 << 20);
      this.pal = null; this.lut = null; this.started = false;
    }

    _push(arr){ this.parts.push(arr instanceof Uint8Array ? arr : new Uint8Array(arr)); }

    /* 15 位元（5-5-5）直方圖 → 中位切割 255 色 → 32768 格最近色查找表 */
    buildPalette(frames){
      const hist = new Uint32Array(32768);
      frames.forEach(f => {
        const step = f.length > 4e5 ? 8 : 4;             // 大影格隔點取樣
        for(let p = 0; p < f.length; p += step) hist[((f[p] >> 3) << 10) | ((f[p + 1] >> 3) << 5) | (f[p + 2] >> 3)]++;
      });
      const cells = [], W8 = new Float32Array(32768);
      for(let i = 0; i < 32768; i++) if(hist[i]){ cells.push(i); W8[i] = Math.sqrt(hist[i]); }   // 開根號：稀有的圖例/軌跡色不被大面積底色吞掉
      const comp = (i, c) => c === 0 ? (i >> 10) & 31 : c === 1 ? (i >> 5) & 31 : i & 31;
      let boxes = [cells];
      const pop = b => b.reduce((s, i) => s + W8[i], 0);
      while(boxes.length < 255){
        let bi = -1, best = 0;
        boxes.forEach((b, k) => {
          if(b.length < 2) return;
          let sc = pop(b);                               // 以人口數為主，優先切最大的盒
          if(sc > best){ best = sc; bi = k; }
        });
        if(bi < 0) break;
        const b = boxes[bi];
        const rng = [0, 1, 2].map(c => { let lo = 31, hi = 0; b.forEach(i => { const v = comp(i, c); if(v < lo) lo = v; if(v > hi) hi = v; }); return hi - lo; });
        const ax = rng.indexOf(Math.max(...rng));
        b.sort((x, y) => comp(x, ax) - comp(y, ax));
        const half = pop(b) / 2; let acc = 0, cut = 1;
        for(let k = 0; k < b.length - 1; k++){ acc += W8[b[k]]; cut = k + 1; if(acc >= half) break; }
        boxes.splice(bi, 1, b.slice(0, cut), b.slice(cut));
      }
      const pal = [];
      boxes.forEach(b => {
        let n = 0, r = 0, g = 0, bl = 0;
        b.forEach(i => { const c = W8[i]; n += c; r += c * comp(i, 0); g += c * comp(i, 1); bl += c * comp(i, 2); });
        n = n || 1;
        pal.push([Math.round(r / n * 8 + 4), Math.round(g / n * 8 + 4), Math.round(bl / n * 8 + 4)].map(v => Math.min(255, v)));
      });
      while(pal.length < 256) pal.push([0, 0, 0]);
      this.pal = pal;
      const lut = new Uint8Array(32768);
      for(let i = 0; i < 32768; i++){
        const r = ((i >> 10) & 31) * 8 + 4, g = ((i >> 5) & 31) * 8 + 4, b = (i & 31) * 8 + 4;
        let bd = 1e9, bk = 0;
        for(let k = 0; k < boxes.length; k++){
          const d = (pal[k][0] - r) ** 2 + (pal[k][1] - g) ** 2 + (pal[k][2] - b) ** 2;
          if(d < bd){ bd = d; bk = k; }
        }
        lut[i] = bk;
      }
      this.lut = lut;
    }

    _header(){
      const w = this.w, h = this.h, b = [];
      b.push(0x47, 0x49, 0x46, 0x38, 0x39, 0x61);                       // GIF89a
      b.push(w & 255, w >> 8, h & 255, h >> 8, 0xF7, 0, 0);            // 全域色盤 256 色
      this.pal.forEach(c => b.push(c[0], c[1], c[2]));
      b.push(0x21, 0xFF, 0x0B, 0x4E, 0x45, 0x54, 0x53, 0x43, 0x41, 0x50, 0x45, 0x32, 0x2E, 0x30,
             0x03, 0x01, 0, 0, 0);                                       // 無限循環
      this._push(b);
    }

    addFrame(rgba){
      if(!this.pal) this.buildPalette([rgba]);
      if(!this.started){ this._header(); this.started = true; }
      const n = this.w * this.h, idx = new Uint8Array(n), lut = this.lut;
      for(let i = 0, p = 0; i < n; i++, p += 4){
        idx[i] = lut[((rgba[p] >> 3) << 10) | ((rgba[p + 1] >> 3) << 5) | (rgba[p + 2] >> 3)];
      }
      const d = this.delay;
      this._push([0x21, 0xF9, 0x04, 0x00, d & 255, d >> 8, 0, 0]);       // 圖形控制
      this._push([0x2C, 0, 0, 0, 0, this.w & 255, this.w >> 8, this.h & 255, this.h >> 8, 0, 8]);
      this._push(this._lzw(idx));
    }

    _lzw(idx){
      const tbl = this.table; tbl.fill(0);
      const out = [];
      let sub = [], cur = 0, curBits = 0, codeSize = 9, next = 258;
      const flushByte = v => { sub.push(v); if(sub.length === 255){ out.push(255, ...sub); sub = []; } };
      const emit = code => {
        cur |= code << curBits; curBits += codeSize;
        while(curBits >= 8){ flushByte(cur & 255); cur >>= 8; curBits -= 8; }
      };
      emit(256);                                                          // clear
      let prefix = idx[0];
      for(let i = 1; i < idx.length; i++){
        const k = idx[i], key = (prefix << 8) | k, hit = tbl[key];
        if(hit){ prefix = hit; continue; }
        emit(prefix);
        if(next < 4096){
          if(next >= (1 << codeSize)) codeSize++;
          tbl[key] = next++;
        } else {
          emit(256); tbl.fill(0); next = 258; codeSize = 9;
        }
        prefix = k;
      }
      emit(prefix); emit(257);
      if(curBits > 0) flushByte(cur & 255);
      if(sub.length) out.push(sub.length, ...sub);
      out.push(0);
      return new Uint8Array(out);
    }

    finish(){
      this._push([0x3B]);
      return new Blob(this.parts, {type: 'image/gif'});
    }
  }
  window.GifEncoder = GifEncoder;
})();
