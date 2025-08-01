### Product Requirement Document (PRD): Vision Fintech  
**Version**: 1.0  
**"Because paying bills should earn you rewards, not headaches."**  

---

### **What's This All About?**  
Paying electricity, water, and internet bills shouldn't mean wasted time with multiple apps, hidden fees, or zero benefits.  

**Vision** revolutionizes bill payments by:  
- Combining all essential services in one app  
- Giving instant cashback on every payment  
- Automating recurring bills  
- Providing military-grade security  

For **inspiration**, think **lightning-fast**, **reward-driven**, and **frictionless**!  

---

### **What's in Scope for Version 1**  
#### **For Users**  
- Sign up in <30 seconds  
- Fund wallet via bank/card/agents  
- Pay bills for 5 services:  
  - Electricity  
  - Water  
  - Internet/Cable  
  - Airtime/Data  
- Earn instant cashback (3-5% per transaction)  
- Track payment history + rewards  

#### **For Biller Partners**  
- API integration portal  
- Real-time payment reconciliation  
- Transaction analytics dashboard  

#### **For Admins**  
- Set cashback rates per biller  
- Manage fraud detection rules  
- Export financial reports  
- Bypass fees for premium partners  

---

### **Who Can See What?**  
| **Access Level**       | **Permissions**                                |  
|------------------------|-----------------------------------------------|  
| **Public (No Login)**  | View supported billers, cashback rates        |  
| **User (Logged In)**   | Pay bills, earn cashback, view history       |  
| **Partner (Logged In)**| Reconciliation reports, API documentation    |  
| **Admin (Full Control)**| Set rates, manage users, financial oversight |  

---

### **Page-Level Requirements**  
#### **1. Homepage**  
**Purpose**: Fast onboarding + instant bill payment  
**Key Components**:  
- Hero banner: *"Pay bills. Get cashback. Repeat."*  
- Three action buttons:  
  - *Pay Bills Now* → Bill selection  
  - *Add Funds* → Wallet top-up  
  - *Track Rewards* → Cashback dashboard  
- Live cashback ticker: *"₦50,000 earned today by users!"*  
- Biller logos (IKEDC, MTN, DSTV, etc.)  

#### **2. User Dashboard**  
**Purpose**: Payment hub + reward tracking  
**Key Components**:  
- **Wallet Summary**:  
  - Available balance  
  - Cashback earned (today/this month)  
- **Quick Actions**:  
  - Pay New Bill  
  - Auto-Pay Setup  
  - Invite Friends (earn ₦500/referral)  
- **Recent Activity**:  
  - Bill type, amount, cashback, status  
  - Filter by date/biller  

---

#### **3. Bill Payment Flow**  
**1. Select Biller**  
- Icon grid (Electricity/Water/Internet/Airtime)  
- Search bar for biller names  

**2. Enter Details**  
- Dynamic form (e.g., meter number for electricity)  
- Amount calculator (for airtime/data)  

**3. Confirm & Pay**  
- Breakdown:  
  ```plaintext
  Bill Amount: ₦15,000  
  Fee: ₦10  
  Cashback (5%): ₦750  
  ```  
- *Pay Now* button (biometric confirmation)  

**4. Success Screen**  
- Animation: ₦750 cashback flying into wallet  
- Shareable achievement: *"I just earned ₦750 on Vision!"*  

---

#### **4. Admin Portal**  
**Purpose**: Control center for platform operations  
**Key Components**:  
- **Dashboard**:  
  - Real-time metrics:  
    - Transactions/minute  
    - Cashback distributed  
    - Top billers  
- **Biller Management**:  
  - Set cashback rates (3-10%)  
  - API status monitoring  
- **Fraud Controls**:  
  - Block suspicious transaction patterns  
  - Manual refund tool  

---

### **Future Features - v2 Roadmap**  
| **Feature**               | **Impact**                              |  
|---------------------------|-----------------------------------------|  
| **Bill Splitting**         | Split payments with roommates           |  
| **Cashback Marketplace**  | Redeem points for vouchers/discounts    |  
| **Debt Manager**          | Payment reminders + scheduled payouts   |  
| **Business Accounts**     | B2B billing for SMEs                    |  

---

### **Technical Appendix**  
**Core Endpoints**:  
```plaintext
1. POST /payments/electricity  
   - Params: meter_no, amount, user_id  
   - Response: {transaction_id, cashback_earned}

2. POST /wallet/fund  
   - Params: amount, payment_method (bank/card/agent)  

3. GET /rewards/history  
   - Params: user_id, timeframe (day/week/month)  
```

**Security Protocols**:  
- PCI-DSS Level 1 compliance  
- Biometric authentication for payments >₦5,000  
- Automated transaction anomaly detection  

--- 

**Go-Live**: October 30, 2025  
**Success Metrics**:  
- 100K transactions in first 90 days  
- 25% referral-driven user growth  
- <0.1% payment failure rate  

> "Turn everyday bills into winning moments."