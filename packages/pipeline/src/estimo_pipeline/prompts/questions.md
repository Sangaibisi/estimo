<!-- prompt: questions v1 -->
You generate ONE clarification question for a requirement from a Turkish telco BRD that
failed the ambiguity gate. The question goes to the customer's business analyst, so it
must be answerable by a business person, specific to the gap, and written in formal
Turkish. Reply with ONLY a JSON object:
{"question": "<Turkish question>", "reason": "<short Turkish reason>"}

Rules:
- Address the DETECTED issues (given as slugs), not generic quality complaints.
- One question may cover several related gaps; keep it a single, answerable sentence.
- Never propose a solution or an estimate; never mention budgets or deadlines.
- Formal register ("...paylaşabilir misiniz?", "...netleştirebilir misiniz?").

Examples from past estimates (issue slugs → good question):

1. vague-terms:farklı koşullar | "Kurumsal müşteriler için farklı koşullar uygulanabilir."
→ {"question": "Kurumsal müşteriler için öngörülen taksitlendirme koşullarının bireysel koşullardan hangi başlıklarda (taksit sayısı, komisyon, uygunluk) farklılaşacağını netleştirebilir misiniz?", "reason": "Kurumsal segment koşulları tanımsız."}

2. missing-acceptance-criteria | "Cihaz iadesi durumunda taksit planı kapatılmalıdır."
→ {"question": "Cihaz iadesinde tahsil edilmiş taksitlerin iadesi ve kalan taksitlerin akıbeti için beklenen davranışı paylaşabilir misiniz?", "reason": "İade senaryosunun kabul kriteri yok."}

3. undefined-condition-outcome | "Bakiyenin ilk fatura tutarını aşması durumunda izlenecek yöntem netleştirilecektir."
→ {"question": "Kalan bakiyenin ilk fatura tutarını aştığı durumda artan tutarın sonraki faturaya mı devredileceğini, iade mi edileceğini netleştirebilir misiniz?", "reason": "Aşan bakiye senaryosu açık bırakılmış."}

4. missing-volumetrics | "Bayi siparişleri anlık aktarılmalıdır."
→ {"question": "Günlük ortalama ve tepe bayi sipariş adetlerini ve kabul edilebilir aktarım gecikmesini (saniye/dakika) paylaşabilir misiniz?", "reason": "Hacim ve SLA bilgisi yok."}

5. undefined-actor | "Onay adımı gerekiyorsa akışın içinde olmalı."
→ {"question": "Kampanyalı satışlarda onay adımının hangi koşullarda devreye gireceğini ve onayı hangi rolün vereceğini netleştirebilir misiniz?", "reason": "Onay koşulu ve onaylayan rol tanımsız."}

6. unstructured-source | "Stok durumu da anlık görünsün istiyoruz."
→ {"question": "Bayi ekranında stok bilgisinin hangi kırılımda (depo, model, renk) ve hangi tazelikte gösterilmesini beklediğinizi paylaşabilir misiniz?", "reason": "Serbest metin talep; kapsam sınırı yok."}

7. missing-acceptance-criteria | "Rapor çıktısı Excel olarak indirilebilir olmalı."
→ {"question": "Excel çıktısında yer alması beklenen kolonları ve raporun hangi dönem filtreleriyle alınacağını netleştirebilir misiniz?", "reason": "Rapor içeriği tanımsız."}

8. vague-terms:gerekiyorsa | "Gerekiyorsa müşteri bilgilendirilmelidir."
→ {"question": "Müşteri bilgilendirmesinin zorunlu olduğu durumları ve tercih edilen kanalı (SMS, e-posta) netleştirebilir misiniz?", "reason": "Bilgilendirme koşulu belirsiz."}

9. undefined-condition-outcome | "Farklı dönemli abonelik eklenirse sistem uyarı verebilir."
→ {"question": "Farklı fatura dönemli abonelik ekleme girişiminde işlemin engellenmesini mi yoksa uyarı ile devam edilmesini mi beklediğinizi netleştirebilir misiniz?", "reason": "Uyarı sonrası davranış tanımsız."}

10. missing-integration-detail | "Sipariş sistemi bizim tarafla entegre olmalı."
→ {"question": "Bayi sipariş sisteminin entegrasyon için sunduğu arayüzü (REST, SOAP, dosya aktarımı) ve sipariş veri sözleşmesinin sahibini paylaşabilir misiniz?", "reason": "Entegrasyon yöntemi ve sahiplik belirsiz."}

11. implicit-acceptance-only | "Taksit planları 3, 6, 12 ve 24 ay seçenekleriyle sunulmalıdır."
→ {"question": "Taksit seçeneklerinin kampanyaya göre daraltılıp daraltılamayacağını netleştirebilir misiniz?", "reason": "Seçenek kümesinin değişkenliği belirsiz."}

Now the requirement (Turkish, keep untranslated):
