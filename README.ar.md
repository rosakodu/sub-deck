# sub-deck

[English](README.md) | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [العربية](README.ar.md) | [فارسی](README.fa.md) | [Türkçe](README.tr.md)

إضافة لـ Decky Loader على جهاز Steam Deck تتيح لك إدارة اشتراكات VLESS و VMess و Trojan و Shadowsocks و Hysteria 2 والاتصال بها مع توجيه TUN التلقائي على مستوى النظام باستخدام `sing-box`.

![Screenshot](assets/screenshot.png)

## 📋 الميزات

- **دعم بروتوكولات متعددة**: VLESS (Reality, TLS, None) و VMess و Trojan و Shadowsocks و Hysteria 2 / Hy2.
- **اشتراكات متعددة**: إضافة وإدارة روابط اشتراك مختلفة في وقت واحد. يتم دمج العقد من جميع الاشتراكات تلقائيًا.
- **توجيه TUN على مستوى النظام**: يقوم بتوجيه جميع حركة مرور الإنترنت الخاصة بـ Steam Deck تلقائيًا عبر واجهة TUN الخاصة بـ `sing-box` (`tun0`).
- **تبديل بنقرة واحدة**: اتصل بمجرد النقر على الخادم في القائمة، وانقر مرة أخرى لقطع الاتصال.
- **سجلات سريعة**: انقر على زر **LOG** لكتابة السجلات المدمجة للإضافة والنواة إلى `/home/deck/sub-deck.log` ونسخها إلى الحافظة.
- **صلاحيات الروت**: يعمل بشكل صحيح كـ `root` لتهيئة الشبكة.
- **لا حاجة لاعتمادات إضافية**: يقوم بتنزيل النواة الأساسية لـ `sing-box` تلقائيًا عند الاتصال الأول.

## 📥 التثبيت

1. قم بتنزيل أحدث إصدار (`sub-deck.zip`) من [الإصدارات](https://github.com/rosakodu/sub-deck/releases) أو قم ببنائه يدويًا.
2. انسخ ملف ZIP إلى جهاز Steam Deck الخاص بك.
3. قم بتمكين **وضع المطور** في إعدادات Steam، ثم في إعدادات Decky Loader، قم بتمكين **Developer mode** واختر "Install plugin from file".

## 🚀 كيفية الاستخدام

1. أدخل رابط الاشتراك الخاص بك (مثل `https://s.subdeck.shop/...`) وانقر على **"Add Subscription"**.
2. انقر على أي خادم في قائمة **"Available Servers"** لتنشيط الاتصال.
3. سيتم تمييز الخادم المحدد، وسيُظهر الملصق العلوي **"Connected to: <name>"**.
4. لقطع الاتصال، ما عليك سوى النقر على الخادم النشط في القائمة مرة أخرى.

## ⚖️ الترخيص

BSD-3-Clause License.
