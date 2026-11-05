/* Financial Lens landing: localisation and the sample treemap. No tracking, no external requests. */
(function () {
  'use strict';

  var T = {
    'en-CH': {
      skip: 'Skip to content', language: 'Language', status: 'Phases 1–4 implemented · open source',
      eyebrow: 'Financial intelligence', title: 'See where the money went. Inspect why.',
      lead: 'Financial Lens is a desktop application for household, business and cooperative finances. It reads receipts, invoices and bank statements, matches invoices with payments and keeps the original document behind every number.',
      ctaDemo: 'Explore the sample treemap', ctaCode: 'Source code',
      howTitle: 'From document to verified record',
      s1t: 'Collect', s1: 'Photos (also HEIC from iPhone), PDFs, CSV and XLSX, camt.053/054 statements, Swiss QR-bills or manual entries — dropped on the app, from a paired phone, a watched folder or forwarded by e-mail.',
      s2t: 'Read', s2: 'OCR and field extraction propose amount, date, counterparty and category, each with its source location and confidence.',
      s3t: 'Reconcile', s3: 'Invoices are matched with bank payments by QR reference, amount and date. Ambiguous cases are left for you to decide.',
      s4t: 'Inspect', s4: 'A treemap shows where money went. Every area opens down to the record, its history and the original document.',
      demoTitle: 'Sample treemap',
      demoNote: 'Illustrative sample data for one fictional household, October 2026. Select an area to drill down; select a record to see its evidence.',
      evTitle: 'Evidence', evEmpty: 'Select a record in the treemap to inspect where its numbers came from.',
      privTitle: 'You choose where your documents go',
      p1t: 'Local only', p1: 'OCR and language models run on your computer. No network connection is used.',
      p2t: 'Swiss hosting', p2: 'Only AI providers hosted in Switzerland may process a document.',
      p3t: 'Cloud AI', p3: 'You allow an external AI provider for better recognition, per document or per workspace.',
      privNote: 'Totals are always calculated deterministically by the application, never by a language model.',
      roadTitle: 'What already works',
      r1: 'Phase 1 — the full cycle: photo or PDF of an invoice → local OCR → record with category → original kept → bank statement → payment matched → treemap → drill down to every piece of evidence.',
      r2: 'Phase 2 — partial and split payments, overpayments, refunds, payslips, duplicates, several currencies at recorded rates, CSV/XLSX bank exports, recurring and overdue payments, period comparisons and questions in plain language.',
      r3: 'Phase 3 — personal, business and cooperative profiles: members, contributions and arrears, earmarked funds, cost allocation per building, roles, projects, budgets, reports and full export.',
      r4: 'Phase 4 — three privacy levels with the network blocked in local-only mode, Swiss or external models only with your consent and with identifiers removed, encrypted backups, tamper-evident audit log, security self-check.',
      ctaDownload: 'Download the app',
      dlTitle: 'Download',
      dlLead: 'A native desktop app. Everything runs on your computer: database, OCR and matching are included, nothing else to install.',
      dlWin: 'Windows 10/11 · installer',
      dlMac: 'macOS 14+ · Apple silicon',
      dlLinux: 'Linux · AppImage',
      dlUnsigned: 'The installers are not code-signed yet. Windows may show “Windows protected your PC” (choose More info → Run anyway); on macOS open the app with right-click → Open the first time. On Linux make the file executable and start it.',
      dlAndroid: 'Android 8+ · phone app (APK)',
      dlIos: 'iPhone · coming via the App Store',
      dlPhone: 'Phone app: pair it with the QR code from the desktop app; photos and scans go straight into your ledger.',
      roadNote: 'Not yet available: accounts, live bank connections and code-signed installers.',
      all: 'All spending', total: 'Total', records: 'records', sample: 'Sample data',
      document: 'Document', location: 'Location', method: 'Method', confidence: 'Confidence',
      payment: 'Bank payment', matched: 'Matched', unmatched: 'No payment found yet',
      quote: 'Recognised text', why: 'Why matched',
      ocr: 'OCR', qr: 'QR-bill (structured)', manual: 'Manual entry', camt: 'camt.053 statement',
      byRef: 'QR reference identical on invoice and payment', byAmount: 'Same amount, booked within the date window',
      Home: 'Home', Rent: 'Rent', Energy: 'Energy', Food: 'Food', Groceries: 'Groceries', Restaurants: 'Restaurants',
      Mobility: 'Mobility', Transport: 'Public transport', Health: 'Health', Insurance: 'Health insurance', Pharmacy: 'Pharmacy'
    },
    'de-CH': {
      skip: 'Zum Inhalt', language: 'Sprache', status: 'Phasen 1–4 umgesetzt · Open Source',
      eyebrow: 'Finanzübersicht', title: 'Sehen, wohin das Geld ging. Prüfen, warum.',
      lead: 'Financial Lens ist eine Desktop-Anwendung für Haushalts-, Geschäfts- und Genossenschaftsfinanzen. Sie liest Quittungen, Rechnungen und Kontoauszüge, ordnet Rechnungen den Zahlungen zu und bewahrt hinter jeder Zahl das Originaldokument auf.',
      ctaDemo: 'Beispiel-Treemap ansehen', ctaCode: 'Quellcode',
      howTitle: 'Vom Dokument zum geprüften Eintrag',
      s1t: 'Sammeln', s1: 'Fotos (auch HEIC vom iPhone), PDFs, CSV und XLSX, camt.053/054-Auszüge, Schweizer QR-Rechnungen oder manuelle Einträge — in die App gezogen, vom gekoppelten Handy, aus einem Ordner oder per E-Mail weitergeleitet.',
      s2t: 'Erkennen', s2: 'OCR und Feldextraktion schlagen Betrag, Datum, Gegenpartei und Kategorie vor, jeweils mit Fundstelle und Konfidenz.',
      s3t: 'Abgleichen', s3: 'Rechnungen werden per QR-Referenz, Betrag und Datum mit Bankzahlungen abgeglichen. Unklare Fälle entscheiden Sie.',
      s4t: 'Prüfen', s4: 'Eine Treemap zeigt, wohin das Geld ging. Jede Fläche öffnet sich bis zum Eintrag, seiner Historie und dem Originaldokument.',
      demoTitle: 'Beispiel-Treemap',
      demoNote: 'Illustrative Beispieldaten eines fiktiven Haushalts, Oktober 2026. Wählen Sie eine Fläche zum Vertiefen und einen Eintrag für seine Belege.',
      evTitle: 'Belege', evEmpty: 'Wählen Sie einen Eintrag in der Treemap, um die Herkunft seiner Zahlen zu prüfen.',
      privTitle: 'Sie bestimmen, wohin Ihre Dokumente gehen',
      p1t: 'Nur lokal', p1: 'OCR und Sprachmodelle laufen auf Ihrem Computer. Es wird keine Netzwerkverbindung genutzt.',
      p2t: 'Schweizer Hosting', p2: 'Nur in der Schweiz gehostete KI-Anbieter dürfen ein Dokument verarbeiten.',
      p3t: 'Cloud-KI', p3: 'Sie erlauben einen externen KI-Anbieter für bessere Erkennung, pro Dokument oder pro Arbeitsbereich.',
      privNote: 'Summen berechnet immer die Anwendung deterministisch, nie ein Sprachmodell.',
      roadTitle: 'Was bereits funktioniert',
      r1: 'Phase 1 — der ganze Ablauf: Foto oder PDF einer Rechnung → lokale OCR → Eintrag mit Kategorie → Original aufbewahrt → Kontoauszug → Zahlung zugeordnet → Treemap → bis zu jedem Beleg vertiefen.',
      r2: 'Phase 2 — Teil- und Mehrfachzahlungen, Überzahlungen, Rückerstattungen, Lohnabrechnungen, Duplikate, Fremdwährungen zu erfassten Kursen, CSV/XLSX-Bankexporte, wiederkehrende und überfällige Zahlungen, Periodenvergleiche und Fragen in Alltagssprache.',
      r3: 'Phase 3 — Profile für Privat, Geschäft und Genossenschaft: Mitglieder, Beiträge und Ausstände, zweckgebundene Fonds, Kostenverteilung pro Haus, Rollen, Projekte, Budgets, Berichte und vollständiger Export.',
      r4: 'Phase 4 — drei Datenschutzstufen mit gesperrtem Netzwerk im Nur-lokal-Modus, Schweizer oder externe Modelle nur mit Ihrer Zustimmung und ohne Identifikatoren, verschlüsselte Backups, manipulationssicheres Protokoll, Sicherheits-Selbsttest.',
      ctaDownload: 'App herunterladen',
      dlTitle: 'Download',
      dlLead: 'Eine native Desktop-App. Alles läuft auf Ihrem Computer: Datenbank, OCR und Abgleich sind dabei, sonst ist nichts zu installieren.',
      dlWin: 'Windows 10/11 · Installationsprogramm',
      dlMac: 'macOS 14+ · Apple Silicon',
      dlLinux: 'Linux · AppImage',
      dlUnsigned: 'Die Installationsprogramme sind noch nicht signiert. Windows zeigt eventuell «Der Computer wurde durch Windows geschützt» (Weitere Informationen → Trotzdem ausführen); unter macOS beim ersten Mal mit Rechtsklick → Öffnen starten. Unter Linux die Datei ausführbar machen und starten.',
      dlAndroid: 'Android 8+ · Handy-App (APK)',
      dlIos: 'iPhone · folgt über den App Store',
      dlPhone: 'Handy-App: mit dem QR-Code aus der Desktop-App koppeln; Fotos und Scans landen direkt in Ihrer Buchhaltung.',
      roadNote: 'Noch nicht verfügbar: Konten, direkte Bankanbindungen und signierte Installationsprogramme.',
      all: 'Alle Ausgaben', total: 'Total', records: 'Einträge', sample: 'Beispieldaten',
      document: 'Dokument', location: 'Fundstelle', method: 'Methode', confidence: 'Konfidenz',
      payment: 'Bankzahlung', matched: 'Zugeordnet', unmatched: 'Noch keine Zahlung gefunden',
      quote: 'Erkannter Text', why: 'Grund der Zuordnung',
      ocr: 'OCR', qr: 'QR-Rechnung (strukturiert)', manual: 'Manueller Eintrag', camt: 'camt.053-Auszug',
      byRef: 'QR-Referenz auf Rechnung und Zahlung identisch', byAmount: 'Gleicher Betrag, im Datumsfenster gebucht',
      Home: 'Wohnen', Rent: 'Miete', Energy: 'Energie', Food: 'Essen', Groceries: 'Lebensmittel', Restaurants: 'Restaurants',
      Mobility: 'Mobilität', Transport: 'Öffentlicher Verkehr', Health: 'Gesundheit', Insurance: 'Krankenkasse', Pharmacy: 'Apotheke'
    },
    'fr-CH': {
      skip: 'Aller au contenu', language: 'Langue', status: 'Phases 1 à 4 réalisées · open source',
      eyebrow: 'Intelligence financière', title: 'Voir où est allé l’argent. Vérifier pourquoi.',
      lead: 'Financial Lens est une application de bureau pour les finances des ménages, des entreprises et des coopératives. Elle lit quittances, factures et relevés bancaires, rapproche les factures des paiements et conserve le document original derrière chaque chiffre.',
      ctaDemo: 'Explorer la treemap d’exemple', ctaCode: 'Code source',
      howTitle: 'Du document à l’écriture vérifiée',
      s1t: 'Collecter', s1: 'Photos (aussi HEIC d’iPhone), PDF, CSV et XLSX, relevés camt.053/054, QR-factures suisses ou saisies manuelles — glissés dans l’app, depuis un téléphone couplé, un dossier surveillé ou transférés par e-mail.',
      s2t: 'Lire', s2: 'L’OCR et l’extraction proposent montant, date, contrepartie et catégorie, chacun avec sa source et son niveau de confiance.',
      s3t: 'Rapprocher', s3: 'Les factures sont rapprochées des paiements par référence QR, montant et date. Les cas ambigus vous reviennent.',
      s4t: 'Examiner', s4: 'Une treemap montre où est allé l’argent. Chaque zone s’ouvre jusqu’à l’écriture, son historique et le document original.',
      demoTitle: 'Treemap d’exemple',
      demoNote: 'Données d’exemple illustratives pour un ménage fictif, octobre 2026. Choisissez une zone pour approfondir, puis une écriture pour voir ses preuves.',
      evTitle: 'Preuves', evEmpty: 'Choisissez une écriture dans la treemap pour voir d’où viennent ses chiffres.',
      privTitle: 'Vous décidez où vont vos documents',
      p1t: 'Local uniquement', p1: 'L’OCR et les modèles de langage tournent sur votre ordinateur. Aucune connexion réseau n’est utilisée.',
      p2t: 'Hébergement suisse', p2: 'Seuls des fournisseurs d’IA hébergés en Suisse peuvent traiter un document.',
      p3t: 'IA dans le cloud', p3: 'Vous autorisez un fournisseur d’IA externe pour une meilleure reconnaissance, par document ou par espace de travail.',
      privNote: 'Les totaux sont toujours calculés de manière déterministe par l’application, jamais par un modèle de langage.',
      roadTitle: 'Ce qui fonctionne déjà',
      r1: 'Phase 1 — le cycle complet : photo ou PDF d’une facture → OCR locale → écriture catégorisée → original conservé → relevé bancaire → paiement rapproché → treemap → jusqu’à chaque preuve.',
      r2: 'Phase 2 — paiements partiels et multiples, trop-perçus, remboursements, fiches de salaire, doublons, devises aux taux enregistrés, exports bancaires CSV/XLSX, paiements récurrents et en retard, comparaisons de périodes et questions en langage courant.',
      r3: 'Phase 3 — profils privé, entreprise et coopérative : membres, cotisations et arriérés, fonds affectés, répartition des coûts par immeuble, rôles, projets, budgets, rapports et export complet.',
      r4: 'Phase 4 — trois niveaux de confidentialité avec réseau bloqué en mode local, modèles suisses ou externes seulement avec votre accord et sans identifiants, sauvegardes chiffrées, journal infalsifiable, autocontrôle de sécurité.',
      ctaDownload: 'Télécharger l’app',
      dlTitle: 'Téléchargement',
      dlLead: 'Une application de bureau native. Tout fonctionne sur votre ordinateur : base de données, OCR et rapprochement sont inclus, rien d’autre à installer.',
      dlWin: 'Windows 10/11 · installateur',
      dlMac: 'macOS 14+ · Apple silicon',
      dlLinux: 'Linux · AppImage',
      dlUnsigned: 'Les installateurs ne sont pas encore signés. Windows peut afficher « Windows a protégé votre ordinateur » (Informations complémentaires → Exécuter quand même) ; sur macOS, ouvrez l’app la première fois par clic droit → Ouvrir. Sous Linux, rendez le fichier exécutable puis lancez-le.',
      dlAndroid: 'Android 8+ · app mobile (APK)',
      dlIos: 'iPhone · bientôt sur l’App Store',
      dlPhone: 'App mobile : couplez-la avec le code QR de l’application de bureau ; photos et scans arrivent directement dans votre registre.',
      roadNote: 'Pas encore disponible : comptes, connexions bancaires directes et installateurs signés.',
      all: 'Toutes les dépenses', total: 'Total', records: 'écritures', sample: 'Données d’exemple',
      document: 'Document', location: 'Emplacement', method: 'Méthode', confidence: 'Confiance',
      payment: 'Paiement bancaire', matched: 'Rapproché', unmatched: 'Aucun paiement trouvé pour l’instant',
      quote: 'Texte reconnu', why: 'Raison du rapprochement',
      ocr: 'OCR', qr: 'QR-facture (structurée)', manual: 'Saisie manuelle', camt: 'Relevé camt.053',
      byRef: 'Référence QR identique sur la facture et le paiement', byAmount: 'Même montant, comptabilisé dans la période',
      Home: 'Logement', Rent: 'Loyer', Energy: 'Énergie', Food: 'Alimentation', Groceries: 'Courses', Restaurants: 'Restaurants',
      Mobility: 'Mobilité', Transport: 'Transports publics', Health: 'Santé', Insurance: 'Caisse maladie', Pharmacy: 'Pharmacie'
    },
    'it-CH': {
      skip: 'Vai al contenuto', language: 'Lingua', status: 'Fasi 1–4 realizzate · open source',
      eyebrow: 'Intelligenza finanziaria', title: 'Vedere dove sono andati i soldi. Verificare perché.',
      lead: 'Financial Lens è un’applicazione desktop per le finanze di economie domestiche, aziende e cooperative. Legge scontrini, fatture ed estratti conto, abbina le fatture ai pagamenti e conserva il documento originale dietro ogni cifra.',
      ctaDemo: 'Esplora la treemap di esempio', ctaCode: 'Codice sorgente',
      howTitle: 'Dal documento alla registrazione verificata',
      s1t: 'Raccogliere', s1: 'Foto (anche HEIC da iPhone), PDF, CSV e XLSX, estratti camt.053/054, QR-fatture svizzere o inserimenti manuali — trascinati nell’app, da un telefono abbinato, da una cartella o inoltrati per e-mail.',
      s2t: 'Leggere', s2: 'OCR ed estrazione propongono importo, data, controparte e categoria, ciascuno con la posizione nella fonte e il grado di affidabilità.',
      s3t: 'Riconciliare', s3: 'Le fatture vengono abbinate ai pagamenti tramite riferimento QR, importo e data. I casi ambigui li decide lei.',
      s4t: 'Esaminare', s4: 'Una treemap mostra dove sono andati i soldi. Ogni area si apre fino alla registrazione, alla sua cronologia e al documento originale.',
      demoTitle: 'Treemap di esempio',
      demoNote: 'Dati di esempio illustrativi per un’economia domestica fittizia, ottobre 2026. Scelga un’area per approfondire e una registrazione per vederne le prove.',
      evTitle: 'Prove', evEmpty: 'Scelga una registrazione nella treemap per vedere da dove provengono le cifre.',
      privTitle: 'Lei decide dove vanno i suoi documenti',
      p1t: 'Solo locale', p1: 'OCR e modelli linguistici funzionano sul suo computer. Non viene usata alcuna connessione di rete.',
      p2t: 'Hosting svizzero', p2: 'Solo fornitori di IA ospitati in Svizzera possono elaborare un documento.',
      p3t: 'IA nel cloud', p3: 'Autorizza un fornitore di IA esterno per un riconoscimento migliore, per documento o per area di lavoro.',
      privNote: 'I totali sono sempre calcolati in modo deterministico dall’applicazione, mai da un modello linguistico.',
      roadTitle: 'Cosa funziona già',
      r1: 'Fase 1 — il ciclo completo: foto o PDF di una fattura → OCR locale → registrazione categorizzata → originale conservato → estratto conto → pagamento abbinato → treemap → fino a ogni prova.',
      r2: 'Fase 2 — pagamenti parziali e multipli, pagamenti in eccesso, rimborsi, buste paga, duplicati, valute ai tassi registrati, esportazioni bancarie CSV/XLSX, pagamenti ricorrenti e scaduti, confronti tra periodi e domande in linguaggio comune.',
      r3: 'Fase 3 — profili privato, azienda e cooperativa: soci, contributi e arretrati, fondi vincolati, ripartizione dei costi per stabile, ruoli, progetti, budget, rapporti ed esportazione completa.',
      r4: 'Fase 4 — tre livelli di privacy con rete bloccata in modalità solo locale, modelli svizzeri o esterni solo con il suo consenso e senza identificativi, backup cifrati, registro a prova di manomissione, autoverifica di sicurezza.',
      ctaDownload: 'Scarica l’app',
      dlTitle: 'Download',
      dlLead: 'Un’app desktop nativa. Tutto funziona sul suo computer: database, OCR e abbinamento sono inclusi, nient’altro da installare.',
      dlWin: 'Windows 10/11 · programma d’installazione',
      dlMac: 'macOS 14+ · Apple silicon',
      dlLinux: 'Linux · AppImage',
      dlUnsigned: 'I programmi d’installazione non sono ancora firmati. Windows potrebbe mostrare «PC protetto da Windows» (Ulteriori informazioni → Esegui comunque); su macOS apra l’app la prima volta con clic destro → Apri. Su Linux renda il file eseguibile e lo avvii.',
      dlAndroid: 'Android 8+ · app per telefono (APK)',
      dlIos: 'iPhone · in arrivo sull’App Store',
      dlPhone: 'App per telefono: la abbini con il codice QR dell’app desktop; foto e scansioni arrivano direttamente nel suo registro.',
      roadNote: 'Non ancora disponibili: account, collegamenti bancari diretti e programmi d’installazione firmati.',
      all: 'Tutte le spese', total: 'Totale', records: 'registrazioni', sample: 'Dati di esempio',
      document: 'Documento', location: 'Posizione', method: 'Metodo', confidence: 'Affidabilità',
      payment: 'Pagamento bancario', matched: 'Abbinato', unmatched: 'Nessun pagamento trovato finora',
      quote: 'Testo riconosciuto', why: 'Motivo dell’abbinamento',
      ocr: 'OCR', qr: 'QR-fattura (strutturata)', manual: 'Inserimento manuale', camt: 'Estratto camt.053',
      byRef: 'Riferimento QR identico su fattura e pagamento', byAmount: 'Stesso importo, contabilizzato nel periodo',
      Home: 'Abitazione', Rent: 'Affitto', Energy: 'Energia', Food: 'Alimentazione', Groceries: 'Spesa', Restaurants: 'Ristoranti',
      Mobility: 'Mobilità', Transport: 'Trasporti pubblici', Health: 'Salute', Insurance: 'Cassa malati', Pharmacy: 'Farmacia'
    },
    'rm': {
      skip: 'Al cuntegn', language: 'Lingua', status: 'Fasas 1–4 realisadas · open source',
      eyebrow: 'Intelligenza finanziala', title: 'Vesair nua ch’ils daners èn ids. Examinar pertge.',
      lead: 'Financial Lens è ina applicaziun da desktop per las finanzas da chasadas, interpresas e cooperativas. Ella legia quittanzas, quints ed extracts bancars, attribuescha ils quints als pajaments e conserva il document original davos mintga cifra.',
      ctaDemo: 'Explorar la treemap d’exempel', ctaCode: 'Code da funtauna',
      howTitle: 'Dal document a l’inscripziun verifitgada',
      s1t: 'Rimnar', s1: 'Fotos (era HEIC dad iPhone), PDFs, CSV ed XLSX, extracts camt.053/054, quints QR svizzers u endataziuns manualas — tratgas en l’app, d’in telefonin collià, d’in ordinatur u tramessas per e-mail.',
      s2t: 'Leger', s2: 'OCR ed extracziun proponan import, data, partenari e categoria, mintgamai cun la posiziun en la funtauna e la fidanza.',
      s3t: 'Cumparegliar', s3: 'Ils quints vegnan cumparegliads cun pajaments bancars tenor referenza QR, import e data. Cas nuncleris decidais Vus.',
      s4t: 'Examinar', s4: 'Ina treemap mussa nua ch’ils daners èn ids. Mintga surfatscha s’avra fin a l’inscripziun, sia istorgia ed il document original.',
      demoTitle: 'Treemap d’exempel',
      demoNote: 'Datas d’exempel illustrativas d’ina chasada fictiva, october 2026. Tscherni ina surfatscha per approfundar ed ina inscripziun per vesair sias cumprovas.',
      evTitle: 'Cumprovas', evEmpty: 'Tscherni ina inscripziun en la treemap per examinar danunder che sias cifras derivan.',
      privTitle: 'Vus decidais nua che Voss documents van',
      p1t: 'Mo local', p1: 'OCR e models linguistics funcziunan sin Voss computer. I na vegn duvrada nagina connexiun da rait.',
      p2t: 'Hosting svizzer', p2: 'Mo purschiders d’IA ospitads en Svizra dastgan elavurar in document.',
      p3t: 'IA en il cloud', p3: 'Vus permettais in purschider d’IA extern per ina meglra renconuschientscha, per document u per lieu da lavur.',
      privNote: 'Las summas calculescha adina l’applicaziun en moda deterministica, mai in model linguistic.',
      roadTitle: 'Quai che funcziuna gia',
      r1: 'Fasa 1 — il ciclus cumplet: foto u PDF d’in quint → OCR local → inscripziun cun categoria → original conservà → extract bancar → pajament attribuì → treemap → fin a mintga cumprova.',
      r2: 'Fasa 2 — pajaments parzials e multiplas, surpajaments, restituziuns, quints da salari, duplicats, valutas tenor curs registrads, exports bancars CSV/XLSX, pajaments regulars e scadids, cumparegliaziuns da periodas e dumondas en lingua quotidiana.',
      r3: 'Fasa 3 — profils privat, interpresa e cooperativa: commembers, contribuziuns e restanzas, fonds liads, repartiziun dals custs per chasa, rollas, projects, budgets, rapports ed export cumplet.',
      r4: 'Fasa 4 — trais nivels da protecziun da datas cun rait bloccada en il modus mo local, models svizzers u externs mo cun Voss consentiment e senza identificaturs, backups criptads, protocol segirà cunter manipulaziuns, autocontroll da segirezza.',
      ctaDownload: 'Telechargiar l’app',
      dlTitle: 'Download',
      dlLead: 'Ina app da desktop nativa. Tut funcziuna sin Voss computer: banca da datas, OCR e cumparegliaziun èn cuntegnids, nagut auter da installar.',
      dlWin: 'Windows 10/11 · program d’installaziun',
      dlMac: 'macOS 14+ · Apple silicon',
      dlLinux: 'Linux · AppImage',
      dlUnsigned: 'Ils programs d’installaziun n’èn anc betg signads. Windows po mussar ina avertiment (Ulteriuras infurmaziuns → Exequir tuttina); sin macOS avri l’app l’emprima giada cun clic dretg → Avrir. Sin Linux faschai la datoteca exequibla e la startai.',
      dlAndroid: 'Android 8+ · app da telefonin (APK)',
      dlIos: 'iPhone · vegn tras l’App Store',
      dlPhone: 'App da telefonin: la colliai cun il code QR da l’app da desktop; fotos e scans arrivan directamain en Voss register.',
      roadNote: 'Anc betg disponibel: contos, colliaziuns bancaras directas e programs d’installaziun signads.',
      all: 'Tut las expensas', total: 'Total', records: 'inscripziuns', sample: 'Datas d’exempel',
      document: 'Document', location: 'Posiziun', method: 'Metoda', confidence: 'Fidanza',
      payment: 'Pajament bancar', matched: 'Attribuì', unmatched: 'Anc nagin pajament chattà',
      quote: 'Text renconuschì', why: 'Raschun da l’attribuziun',
      ocr: 'OCR', qr: 'Quint QR (structurà)', manual: 'Endataziun manuala', camt: 'Extract camt.053',
      byRef: 'Referenza QR identica sin quint e pajament', byAmount: 'Medem import, registrà en la perioda',
      Home: 'Abitar', Rent: 'Fittanza', Energy: 'Energia', Food: 'Nutriment', Groceries: 'Victualias', Restaurants: 'Ustarias',
      Mobility: 'Mobilitad', Transport: 'Traffic public', Health: 'Sanadad', Insurance: 'Cassa da malsauns', Pharmacy: 'Apoteca'
    }
  };

  // Fictional sample: amounts in CHF, each leaf is a record with its evidence.
  var DATA = { key: 'all', children: [
    { key: 'Home', children: [
      { key: 'Rent', records: [
        { id: 'R-101', label: 'Wohnbau Genossenschaft Sihlfeld', amount: 1850.00, date: '2026-10-01', method: 'qr', doc: 'qr-bill_2026-10_miete.pdf', loc: 'QR code, payment part', conf: null,
          quote: 'SPC · 0200 · CH44 3199 9123 0008 8901 2 · 1850.00 CHF · QRR 21 00000 00003 13947 14300 09017', pay: { date: '2026-09-30', ref: 'camt.053 Ntry[2]', rule: 'byRef' } } ] },
      { key: 'Energy', records: [
        { id: 'R-102', label: 'Elektrizitätswerk (fictional)', amount: 129.40, date: '2026-10-12', method: 'ocr', doc: 'IMG_2041.jpg', loc: 'page 1, lines 18–21', conf: 0.94,
          quote: 'Total zu bezahlen   CHF 129.40\nZahlbar bis 30.10.2026', pay: { date: '2026-10-28', ref: 'camt.053 Ntry[9]', rule: 'byAmount' } } ] } ] },
    { key: 'Food', children: [
      { key: 'Groceries', records: [
        { id: 'R-201', label: 'Supermarket receipt', amount: 54.20, date: '2026-10-14', method: 'ocr', doc: 'receipt_2026-10-14.jpg', loc: 'page 1, line 31', conf: 0.88,
          quote: 'TOTAL CHF      54.20\nKarte ****1234', pay: { date: '2026-10-14', ref: 'camt.053 Ntry[5]', rule: 'byAmount' } },
        { id: 'R-202', label: 'Weekly market', amount: 38.50, date: '2026-10-18', method: 'manual', doc: null, loc: '—', conf: null, quote: null, pay: null },
        { id: 'R-203', label: 'Supermarket receipt', amount: 112.85, date: '2026-10-25', method: 'ocr', doc: 'receipt_2026-10-25.pdf', loc: 'page 1, line 44', conf: 0.91,
          quote: 'Total       112.85', pay: { date: '2026-10-25', ref: 'camt.053 Ntry[12]', rule: 'byAmount' } } ] },
      { key: 'Restaurants', records: [
        { id: 'R-204', label: 'Café receipt', amount: 46.00, date: '2026-10-09', method: 'ocr', doc: 'IMG_2033.jpg', loc: 'page 1, line 12', conf: 0.79,
          quote: 'Summe CHF 46.00', pay: { date: '2026-10-09', ref: 'camt.053 Ntry[4]', rule: 'byAmount' } } ] } ] },
    { key: 'Mobility', children: [
      { key: 'Transport', records: [
        { id: 'R-301', label: 'Half-fare travelcard renewal', amount: 190.00, date: '2026-10-03', method: 'ocr', doc: 'ticket_2026-10-03.pdf', loc: 'page 1, line 7', conf: 0.97,
          quote: 'Preis CHF 190.00', pay: { date: '2026-10-03', ref: 'camt.053 Ntry[3]', rule: 'byAmount' } } ] } ] },
    { key: 'Health', children: [
      { key: 'Insurance', records: [
        { id: 'R-401', label: 'Health insurer premium', amount: 412.60, date: '2026-10-01', method: 'qr', doc: 'praemie_2026-10.pdf', loc: 'QR code, payment part', conf: null,
          quote: 'SPC · 0200 · 412.60 CHF · QRR 21 00000 00003 13947 14300 09025', pay: { date: '2026-10-01', ref: 'camt.053 Ntry[1]', rule: 'byRef' } } ] },
      { key: 'Pharmacy', records: [
        { id: 'R-402', label: 'Pharmacy receipt', amount: 27.90, date: '2026-10-21', method: 'ocr', doc: 'IMG_2058.jpg', loc: 'page 1, line 9', conf: 0.83,
          quote: 'Total CHF 27.90', pay: null } ] } ] }
  ] };

  var lang = 'en-CH';
  var path = [DATA];
  var selected = null;

  function t(k) { return (T[lang] && T[lang][k]) || T['en-CH'][k] || k; }
  function cents(n) { return Math.round(n * 100); }
  function sum(node) {
    if (node._c != null) return node._c;
    var c = 0;
    (node.children || []).forEach(function (x) { c += sum(x); });
    (node.records || []).forEach(function (r) { c += cents(r.amount); });
    node._c = c; return c;
  }
  function chf(c) {
    var s = (Math.abs(c) / 100).toFixed(2).split('.');
    return 'CHF ' + s[0].replace(/\B(?=(\d{3})+(?!\d))/g, '’') + '.' + s[1];
  }
  function name(n) { return n.key === 'all' ? t('all') : t(n.key); }
  function items(node) {
    var list = (node.children || []).map(function (c) { return { node: c, value: sum(c), label: name(c) }; });
    (node.records || []).forEach(function (r) { list.push({ record: r, value: cents(r.amount), label: r.label }); });
    return list.sort(function (a, b) { return b.value - a.value; });
  }

  // Squarified treemap layout (Bruls et al.), on percentages of the container.
  function squarify(list, x, y, w, h, out) {
    if (!list.length) return out;
    var total = list.reduce(function (s, i) { return s + i.value; }, 0);
    var area = w * h;
    var scaled = list.map(function (i) { return i.value / total * area; });
    var row = [], i = 0;
    function worst(r, side) {
      var s = r.reduce(function (a, b) { return a + b; }, 0), mx = Math.max.apply(null, r), mn = Math.min.apply(null, r);
      return Math.max(side * side * mx / (s * s), (s * s) / (side * side * mn));
    }
    var side = Math.min(w, h);
    while (i < scaled.length && (row.length === 0 || worst(row.concat(scaled[i]), side) <= worst(row, side))) { row.push(scaled[i]); i++; }
    var rs = row.reduce(function (a, b) { return a + b; }, 0);
    var off = 0;
    row.forEach(function (a, k) {
      var it = list[k];
      if (w >= h) { var cw = rs / h, ch = a / cw; out.push({ it: it, x: x, y: y + off, w: cw, h: ch }); off += ch; }
      else { var rh = rs / w, rw = a / rh; out.push({ it: it, x: x + off, y: y, w: rw, h: rh }); off += rw; }
    });
    if (w >= h) squarify(list.slice(row.length), x + rs / h, y, w - rs / h, h, out);
    else squarify(list.slice(row.length), x, y + rs / w, w, h - rs / w, out);
    return out;
  }

  var shades = ['--surface-secondary', '--surface-raised', '--brand-soft', '--hl-slate'];

  function render(refract) {
    var node = path[path.length - 1];
    var box = document.getElementById('treemap');
    box.textContent = '';
    box.classList.remove('refract');
    if (refract) { void box.offsetWidth; box.classList.add('refract'); }
    squarify(items(node), 0, 0, 100, 100, []).forEach(function (r, k) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'tile' + (r.it.record ? ' leaf' : '');
      b.style.left = r.x + '%'; b.style.top = r.y + '%'; b.style.width = r.w + '%'; b.style.height = r.h + '%';
      b.style.background = 'var(' + shades[k % shades.length] + ')';
      if (r.it.record && selected === r.it.record.id) b.style.outline = '2px solid var(--text-primary)';
      var strong = document.createElement('strong'); strong.textContent = r.it.label;
      var span = document.createElement('span'); span.textContent = chf(r.it.value);
      b.append(strong, span);
      b.setAttribute('aria-label', r.it.label + ', ' + chf(r.it.value));
      b.addEventListener('click', function () {
        if (r.it.node) { path.push(r.it.node); selected = null; render(true); showEvidence(null); }
        else { selected = r.it.record.id; render(false); showEvidence(r.it.record); }
      });
      box.appendChild(b);
    });
    var crumbs = document.getElementById('crumbs');
    crumbs.textContent = '';
    path.forEach(function (p, i) {
      if (i) { var s = document.createElement('span'); s.textContent = '/'; s.setAttribute('aria-hidden', 'true'); crumbs.appendChild(s); }
      var c = document.createElement('button'); c.type = 'button'; c.textContent = name(p);
      if (i === path.length - 1) c.setAttribute('aria-current', 'page');
      c.addEventListener('click', function () { if (i < path.length - 1) { path = path.slice(0, i + 1); selected = null; render(true); showEvidence(null); } });
      crumbs.appendChild(c);
    });
    var n = 0; (function count(x) { n += (x.records || []).length; (x.children || []).forEach(count); })(node);
    document.getElementById('total').textContent = t('total') + ' ' + chf(sum(node)) + ' · ' + n + ' ' + t('records') + ' · ' + t('sample');
  }

  function row(dl, k, v) {
    var dt = document.createElement('dt'); dt.textContent = t(k);
    var dd = document.createElement('dd'); dd.textContent = v;
    dl.append(dt, dd);
  }

  function showEvidence(r) {
    var el = document.getElementById('evidence');
    el.textContent = '';
    var h = document.createElement('h3'); h.textContent = t('evTitle'); el.appendChild(h);
    if (!r) { var p = document.createElement('p'); p.className = 'muted'; p.textContent = t('evEmpty'); el.appendChild(p); return; }
    var title = document.createElement('p'); title.className = 'num';
    title.innerHTML = '<strong></strong><br><span class="meta"></span>';
    title.querySelector('strong').textContent = r.label;
    title.querySelector('span').textContent = r.id + ' · ' + r.date + ' · ' + chf(cents(r.amount));
    el.appendChild(title);
    var dl = document.createElement('dl');
    row(dl, 'document', r.doc || '—');
    row(dl, 'location', r.loc);
    row(dl, 'method', t(r.method));
    if (r.conf != null) row(dl, 'confidence', Math.round(r.conf * 100) + ' %');
    el.appendChild(dl);
    if (r.quote) {
      var q = document.createElement('p'); q.className = 'meta'; q.textContent = t('quote'); el.appendChild(q);
      var bq = document.createElement('blockquote'); bq.textContent = r.quote; el.appendChild(bq);
    }
    var pay = document.createElement('p');
    var badge = document.createElement('span');
    if (r.pay) {
      badge.className = 'badge ok'; badge.textContent = t('matched');
      pay.append(badge, document.createTextNode(' ' + t('payment') + ' ' + r.pay.date + ' · ' + t('camt') + ' ' + r.pay.ref.replace('camt.053 ', '')));
      el.appendChild(pay);
      var why = document.createElement('p'); why.className = 'meta'; why.textContent = t('why') + ': ' + t(r.pay.rule); el.appendChild(why);
    } else {
      badge.className = 'badge warn'; badge.textContent = t('unmatched'); pay.appendChild(badge); el.appendChild(pay);
    }
  }

  function applyLang(l) {
    lang = T[l] ? l : 'en-CH';
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach(function (n) { n.textContent = t(n.getAttribute('data-i18n')); });
    document.getElementById('lang').value = lang;
    try { localStorage.setItem('fl-lang', lang); } catch (e) { /* storage unavailable */ }
    render(false);
    var rec = null;
    (function find(x) { (x.records || []).forEach(function (r) { if (r.id === selected) rec = r; }); (x.children || []).forEach(find); })(DATA);
    showEvidence(rec);
  }

  function initialLang() {
    try { var s = localStorage.getItem('fl-lang'); if (s && T[s]) return s; } catch (e) { /* ignore */ }
    var nav = (navigator.languages || [navigator.language || 'en']).map(function (x) { return x.toLowerCase(); });
    for (var i = 0; i < nav.length; i++) {
      var p = nav[i].slice(0, 2);
      if (p === 'de') return 'de-CH'; if (p === 'fr') return 'fr-CH'; if (p === 'it') return 'it-CH'; if (p === 'rm') return 'rm'; if (p === 'en') return 'en-CH';
    }
    return 'en-CH';
  }

  document.getElementById('lang').addEventListener('change', function (e) { applyLang(e.target.value); });
  applyLang(initialLang());
})();
