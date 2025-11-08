#!/usr/bin/env python3
"""
Testdaten für Multi-Bestand POS-System erstellen
Erstellt alle 4 Reseller-Typen + Marktbestand
"""

from app import create_app
from models import db, User, Customer, Product, ConsignmentStock
from werkzeug.security import generate_password_hash
from decimal import Decimal

app = create_app()

with app.app_context():
    print("🚀 Erstelle Testdaten für Reseller-System...\n")
    
    # ==========================================================================
    # 1. Produkte erstellen (falls noch nicht vorhanden)
    # ==========================================================================
    products_data = [
        {'name': 'Waldhonig 500g', 'price': 8.50, 'number': 100, 'tax_rate': 7.0},
        {'name': 'Blütenhonig 500g', 'price': 7.50, 'number': 150, 'tax_rate': 7.0},
        {'name': 'Rapshonig 500g', 'price': 6.50, 'number': 80, 'tax_rate': 7.0},
        {'name': 'Akazienhonig 500g', 'price': 9.50, 'number': 50, 'tax_rate': 7.0},
        {'name': 'Propolis Tinktur 50ml', 'price': 12.00, 'number': 30, 'tax_rate': 19.0},
    ]
    
    products = []
    for p_data in products_data:
        product = Product.query.filter_by(name=p_data['name']).first()
        if not product:
            product = Product(
                name=p_data['name'],
                price=p_data['price'],
                number=p_data['number'],
                tax_rate=p_data['tax_rate'],
                active=True
            )
            db.session.add(product)
            print(f"✅ Produkt erstellt: {p_data['name']}")
        else:
            print(f"ℹ️  Produkt existiert: {p_data['name']}")
        products.append(product)
    
    db.session.commit()
    
    # ==========================================================================
    # 2. Marktstand-Customer (wird schon bei init-db erstellt, aber sicher ist sicher)
    # ==========================================================================
    marktstand = Customer.query.filter_by(email='marktstand@system.local').first()
    if not marktstand:
        marktstand = Customer(
            company_name='Marktstand',
            first_name='Markt',
            last_name='Bestand',
            email='marktstand@system.local',
            address='Interner Bestand für Marktverkäufe'
        )
        db.session.add(marktstand)
        db.session.commit()
        print("✅ Marktstand-Customer erstellt")
    else:
        print(f"ℹ️  Marktstand-Customer existiert (ID: {marktstand.id})")
    
    # ==========================================================================
    # 3. Reseller-Customer für Typ 1-3
    # ==========================================================================
    resellers_data = [
        {
            'type': 'type1_ust_extern',
            'company': 'Biomarkt Schmidt GmbH',
            'first_name': 'Thomas',
            'last_name': 'Schmidt',
            'email': 'schmidt@biomarkt.de'
        },
        {
            'type': 'type2_non_ust_extern',
            'company': 'Hofladen Müller',
            'first_name': 'Anna',
            'last_name': 'Müller',
            'email': 'mueller@hofladen.de'
        },
        {
            'type': 'type3_non_ust_pwa',
            'company': 'Wochenmarkt Weber',
            'first_name': 'Klaus',
            'last_name': 'Weber',
            'email': 'weber@wochenmarkt.de'
        }
    ]
    
    reseller_customers = {}
    for r_data in resellers_data:
        customer = Customer.query.filter_by(email=r_data['email']).first()
        if not customer:
            customer = Customer(
                company_name=r_data['company'],
                first_name=r_data['first_name'],
                last_name=r_data['last_name'],
                email=r_data['email'],
                address=f"Testadresse {r_data['last_name']}"
            )
            db.session.add(customer)
            db.session.flush()
            print(f"✅ Reseller-Customer erstellt: {r_data['company']}")
        else:
            print(f"ℹ️  Reseller-Customer existiert: {r_data['company']}")
        reseller_customers[r_data['type']] = customer
    
    db.session.commit()
    
    # ==========================================================================
    # 4. User für jeden Reseller-Typ erstellen
    # ==========================================================================
    users_data = [
        {
            'username': 'reseller_type1',
            'email': 'type1@test.local',
            'password': 'test123',
            'reseller_type': 'type1_ust_extern',
            'customer': reseller_customers['type1_ust_extern'],
            'description': 'USt.-pflichtig mit eigenem System'
        },
        {
            'username': 'reseller_type2',
            'email': 'type2@test.local',
            'password': 'test123',
            'reseller_type': 'type2_non_ust_extern',
            'customer': reseller_customers['type2_non_ust_extern'],
            'description': 'Nicht USt.-pflichtig ohne PWA'
        },
        {
            'username': 'reseller_type3',
            'email': 'type3@test.local',
            'password': 'test123',
            'reseller_type': 'type3_non_ust_pwa',
            'customer': reseller_customers['type3_non_ust_pwa'],
            'description': 'Nicht USt.-pflichtig mit PWA (nur Bestandsumbuchung)'
        },
        {
            'username': 'owner_market',
            'email': 'owner@test.local',
            'password': 'test123',
            'reseller_type': 'type4_owner_market',
            'customer': marktstand,
            'description': 'Owner auf Markt (Bestandsumbuchung + BAR-Rechnung)'
        }
    ]
    
    for u_data in users_data:
        user = User.query.filter_by(username=u_data['username']).first()
        if not user:
            user = User(
                username=u_data['username'],
                email=u_data['email'],
                password_hash=generate_password_hash(u_data['password']),
                role='cashier',
                is_active=True,
                reseller_type=u_data['reseller_type'],
                reseller_customer_id=u_data['customer'].id
            )
            db.session.add(user)
            print(f"✅ User erstellt: {u_data['username']} ({u_data['description']})")
        else:
            print(f"ℹ️  User existiert: {u_data['username']}")
    
    db.session.commit()
    
    # ==========================================================================
    # 5. ConsignmentStock für Typ 3 Reseller befüllen
    # ==========================================================================
    print("\n📦 Befülle Marktbestände...\n")
    
    # Typ 3 Reseller: Wochenmarkt Weber
    type3_customer = reseller_customers['type3_non_ust_pwa']
    type3_stock_data = [
        {'product': products[0], 'quantity': 10, 'unit_price': 10.00},  # Waldhonig teurer
        {'product': products[1], 'quantity': 15, 'unit_price': 9.00},   # Blütenhonig teurer
        {'product': products[2], 'quantity': 8, 'unit_price': 8.00},    # Rapshonig teurer
    ]
    
    for stock_data in type3_stock_data:
        stock = ConsignmentStock.query.filter_by(
            customer_id=type3_customer.id,
            product_id=stock_data['product'].id
        ).first()
        
        if not stock:
            stock = ConsignmentStock(
                customer_id=type3_customer.id,
                product_id=stock_data['product'].id,
                quantity=stock_data['quantity'],
                unit_price=Decimal(str(stock_data['unit_price'])),
                quantity_sold=0
            )
            db.session.add(stock)
            print(f"✅ ConsignmentStock: {stock_data['product'].name} → {type3_customer.company_name} ({stock_data['quantity']} Stk @ {stock_data['unit_price']}€)")
        else:
            print(f"ℹ️  ConsignmentStock existiert: {stock_data['product'].name}")
    
    # Owner Marktbestand (für owner_market User)
    owner_stock_data = [
        {'product': products[0], 'quantity': 20, 'unit_price': 8.50},   # Waldhonig Normalpreis
        {'product': products[1], 'quantity': 25, 'unit_price': 7.50},   # Blütenhonig Normalpreis
        {'product': products[3], 'quantity': 10, 'unit_price': 9.50},   # Akazienhonig
        {'product': products[4], 'quantity': 5, 'unit_price': 12.00},   # Propolis
    ]
    
    for stock_data in owner_stock_data:
        stock = ConsignmentStock.query.filter_by(
            customer_id=marktstand.id,
            product_id=stock_data['product'].id
        ).first()
        
        if not stock:
            stock = ConsignmentStock(
                customer_id=marktstand.id,
                product_id=stock_data['product'].id,
                quantity=stock_data['quantity'],
                unit_price=Decimal(str(stock_data['unit_price'])),
                quantity_sold=0
            )
            db.session.add(stock)
            print(f"✅ Marktbestand: {stock_data['product'].name} → {marktstand.company_name} ({stock_data['quantity']} Stk @ {stock_data['unit_price']}€)")
        else:
            print(f"ℹ️  Marktbestand existiert: {stock_data['product'].name}")
    
    db.session.commit()
    
    # ==========================================================================
    # Zusammenfassung
    # ==========================================================================
    print("\n" + "="*70)
    print("✅ Testdaten erfolgreich erstellt!\n")
    print("Login-Daten:\n")
    print("👤 Admin (alle Rechte):")
    print("   Username: admin")
    print("   Password: admin")
    print()
    print("👤 Typ 1 - USt.-pflichtig extern (kein POS-Zugriff):")
    print("   Username: reseller_type1")
    print("   Password: test123")
    print()
    print("👤 Typ 2 - Nicht USt.-pflichtig extern (kein POS-Zugriff):")
    print("   Username: reseller_type2")
    print("   Password: test123")
    print()
    print("👤 Typ 3 - Nicht USt.-pflichtig mit PWA (nur Bestandsumbuchung):")
    print("   Username: reseller_type3")
    print("   Password: test123")
    print("   → POS zeigt Marktbestand, KEINE Rechnung bei Verkauf")
    print()
    print("👤 Typ 4 - Owner auf Markt (Bestandsumbuchung + BAR-Rechnung):")
    print("   Username: owner_market")
    print("   Password: test123")
    print("   → Bei Login: Bestandsauswahl (Haupt oder Markt)")
    print("   → POS erstellt BAR-Rechnung (GoBD-konform)")
    print()
    print("="*70)
