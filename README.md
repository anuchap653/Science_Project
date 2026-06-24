# Science Project

โปรเจกต์จำลองระบบนิเวศ (หญ้า–กระต่าย–หมาป่า) ด้วย **Streamlit** พร้อมระบบโหวตสดจากผู้ใช้งาน

## โครงสร้างโปรเจกต์

```text
Science_Project/
├── README.md
├── .gitignore
└── Science_Project/
    ├── app.py
    ├── requirements.txt
    └── image/
```

## ความสามารถหลัก

- จำลองประชากรหญ้า กระต่าย หมาป่า แบบเรียลไทม์
- มีแผนภาพและแผนที่แสดงผลการจำลอง
- มีระบบโหวต Team Rabbit / Team Wolf
- รองรับเหตุการณ์พิเศษ เช่น ไฟป่า ภัยแล้ง

## วิธีติดตั้งและรัน

1. เข้าโฟลเดอร์โปรเจกต์
2. ติดตั้ง dependencies
3. รันแอปด้วย Streamlit

```bash
cd Science_Project
pip install -r requirements.txt
streamlit run app.py
```

## โหมดการใช้งาน

- โหมดจำลองหลัก: เปิดแอปตามปกติ
- โหมดโหวต: เพิ่ม query `?mode=vote` ที่ URL

## หมายเหตุ

- ไฟล์ฐานข้อมูลโหวต (`votes.db`) จะถูกสร้างอัตโนมัติระหว่างใช้งาน
- ไฟล์ cache/runtime ถูกตั้งค่าไม่ให้ tracked ใน Git เพื่อให้ repository สะอาดขึ้น
