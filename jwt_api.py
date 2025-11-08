# JWT API für PWA
# Dieses Modul stellt Token-basierte Authentifizierung für die Progressive Web App bereit

import jwt
import datetime
from functools import wraps
from flask import request, jsonify, current_app
from models import User

def generate_jwt_token(user_id, expires_in_days=30):
    """
    Generiert ein JWT Token für einen User
    
    Args:
        user_id: User ID
        expires_in_days: Gültigkeit in Tagen (Standard: 30)
        
    Returns:
        JWT Token als String
    """
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=expires_in_days),
        'iat': datetime.datetime.utcnow()
    }
    
    token = jwt.encode(
        payload,
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )
    
    return token

def verify_jwt_token(token):
    """
    Verifiziert ein JWT Token
    
    Args:
        token: JWT Token String
        
    Returns:
        User object oder None
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config['SECRET_KEY'],
            algorithms=['HS256']
        )
        
        user = User.query.get(payload['user_id'])
        
        if user and user.is_active:
            return user
        return None
        
    except jwt.ExpiredSignatureError:
        return None  # Token abgelaufen
    except jwt.InvalidTokenError:
        return None  # Ungültiges Token

def token_required(f):
    """
    Decorator für API-Routen die JWT-Authentifizierung erfordern
    
    Usage:
        @app.route('/api/protected')
        @token_required
        def protected_route(current_user):
            return jsonify({'user': current_user.username})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Token aus Header lesen
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                # Format: "Bearer <token>"
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format. Use: Bearer <token>'}), 401
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        # Token verifizieren
        current_user = verify_jwt_token(token)
        
        if not current_user:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # User als Parameter an die Route übergeben
        return f(current_user, *args, **kwargs)
    
    return decorated

def role_required_api(*allowed_roles):
    """
    Decorator für API-Routen die bestimmte Rollen erfordern
    
    Usage:
        @app.route('/api/admin')
        @token_required
        @role_required_api('admin')
        def admin_route(current_user):
            return jsonify({'message': 'Admin access'})
    """
    def decorator(f):
        @wraps(f)
        def decorated(current_user, *args, **kwargs):
            if not current_user.has_role(*allowed_roles):
                return jsonify({
                    'error': 'Insufficient permissions',
                    'required_roles': list(allowed_roles),
                    'your_role': current_user.role
                }), 403
            
            return f(current_user, *args, **kwargs)
        
        return decorated
    return decorator
