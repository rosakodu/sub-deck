# sub-deck

[English](README.md) | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [العربية](README.ar.md) | [فارسی](README.fa.md) | [Türkçe](README.tr.md)

Steam Deck için Decky Loader eklentisi. VLESS, VMess, Trojan, Shadowsocks ve Hysteria 2 aboneliklerinizi yönetmenizi ve `sing-box` kullanarak otomatik sistem genelinde TUN yönlendirmesiyle bunlara bağlanmanızı sağlar.

![Screenshot](assets/screenshot.png)

## 📋 Özellikler

- **Çoklu Protokol Desteği**: VLESS (Reality, TLS, None), VMess, Trojan, Shadowsocks ve Hysteria 2 / Hy2.
- **Birden Fazla Abonelik**: Farklı abonelik bağlantılarını aynı anda ekleyin ve yönetin. Tüm aboneliklerdeki düğümler otomatik olarak birleştirilir.
- **Sistem Genelinde TUN Yönlendirmesi**: Tüm Steam Deck internet trafiğini otomatik olarak `sing-box` TUN arayüzü (`tun0`) üzerinden yönlendirir.
- **Tek Tıkla Bağlantı**: Listeden sunucuya tıklayarak bağlanın, bağlantıyı kesmek için tekrar tıklayın.
- **Hızlı Loglama**: Eklenti ve çekirdek loglarını `/home/deck/sub-deck.log` dosyasına yazmak ve panoya kopyalamak için **LOG** düğmesine tıklayın.
- **Root Ayrıcalıkları**: Ağ yapılandırması için sorunsuz şekilde `root` olarak çalışır.
- **Bağımlılık Gerektirmez**: İlk bağlantıda `sing-box` çekirdek ikili dosyasını otomatik olarak indirir.

## 📥 Kurulum

1. [Sürümler (Releases)](https://github.com/rosakodu/sub-deck/releases) sayfasından en son sürümü (`sub-deck.zip`) indirin veya manuel olarak derleyin.
2. ZIP dosyasını Steam Deck'inize kopyalayın.
3. Steam Ayarlarında **Geliştirici Modunu (Developer Mode)** etkinleştirin, ardından Decky Loader ayarlarında **Developer mode**'u açın ve "Install plugin from file" seçeneğini belirleyin.

## 🚀 Nasıl Kullanılır

1. Abonelik URL'nizi girin (ör. `https://...`) ve **"Add Subscription"** düğmesine tıklayın.
2. Bağlantıyı etkinleştirmek için **"Available Servers"** listesindeki herhangi bir sunucuya tıklayın.
3. Seçilen sunucu vurgulanacak ve üst etikette **"Connected to: <name>"** gösterilecektir.
4. Bağlantıyı kesmek için listedeki aktif sunucuya tekrar tıklamanız yeterlidir.

## ⚖️ Lisans

BSD-3-Clause Lisansı.
