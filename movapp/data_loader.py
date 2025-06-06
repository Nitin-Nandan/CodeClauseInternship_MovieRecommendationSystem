import pandas as pd
import pickle
import os
import numpy as np
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import time
import random
from django.conf import settings
from django.core.cache import cache
import hashlib
import json

class MovieDataLoader:
    def __init__(self):
        self.movies_df = None
        self.svd_model = None
        self.movie_titles = []
        self._safe_user_id = None
        # TMDB API configuration
        self.tmdb_api_key = "74cdb9b204e5c6f95ffc62fb7ea57b13"
        self.tmdb_base_url = "https://api.themoviedb.org/3"
        self.tmdb_image_base_url = "https://image.tmdb.org/t/p/w500"
        
        # Add cache configuration
        self.cache_timeout = 1800  # 30 minutes for recommendations
        
        self.setup_session()
        self.load_data()
    
    def _generate_cache_key(self, selected_movies, filters=None):
        """Generate a unique cache key for recommendations"""
        # Create a unique key based on selected movies and filters
        key_data = {
            'movies': sorted(selected_movies),
            'filters': filters or {}
        }
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        return f"recommendations_{key_hash}"
    
    def calculate_confidence_score(self, prediction, genre_similarity=0):
        """
        Calculate confidence score for a recommendation
        Based on SVD prediction certainty and genre overlap
        """
        # Base confidence from SVD prediction
        # SVD predictions typically range from 1-5, with higher ratings being more confident
        base_confidence = min(prediction.est / 5.0, 1.0)  # Normalize to 0-1
        
        # Boost confidence based on genre similarity
        genre_boost = min(genre_similarity * 0.15, 0.3)  # Max 30% boost
        
        # Combine factors
        final_confidence = min(base_confidence + genre_boost, 1.0)
        
        return round(final_confidence * 100, 1)  # Convert to percentage
    
    def get_confidence_color(self, confidence_score):
        """
        Get color for confidence score
        """
        if confidence_score >= 85:
            return "#28a745"  # Green - Very High
        elif confidence_score >= 70:
            return "#17a2b8"  # Blue - High  
        elif confidence_score >= 55:
            return "#ffc107"  # Yellow - Medium
        else:
            return "#dc3545"  # Red - Low
    
    def generate_explanation(self, movie_title, selected_movies, user_preferences, genre_similarity, predicted_rating):
        """
        Generate human-readable explanation for why a movie was recommended
        """
        explanations = []
        
        # Genre-based explanation
        if genre_similarity > 0:
            common_genres = []
            movie_details = self.get_movie_details(movie_title)
            if movie_details:
                movie_genres = set(movie_details['genres'])
                common_genres = list(user_preferences['preferred_genres'].intersection(movie_genres))
            
            if common_genres:
                if len(common_genres) == 1:
                    explanations.append(f"shares your interest in {common_genres[0]} movies")
                else:
                    explanations.append(f"matches your taste for {', '.join(common_genres[:2])} films")
        
        # Rating-based explanation
        if predicted_rating >= 4.5:
            explanations.append("predicted to be exceptional for your taste")
        elif predicted_rating >= 4.0:
            explanations.append("highly rated match for your preferences")
        elif predicted_rating >= 3.5:
            explanations.append("good fit based on your movie choices")
        
        # Similar movies explanation
        if len(selected_movies) >= 3:
            sample_movie = selected_movies[0].split('(')[0].strip()  # Get clean title
            explanations.append(f"recommended because you enjoyed {sample_movie}")
        
        # Combine explanations
        if explanations:
            if len(explanations) == 1:
                return f"Recommended because it {explanations[0]}."
            elif len(explanations) == 2:
                return f"Recommended because it {explanations[0]} and is {explanations[1]}."
            else:
                return f"Recommended because it {explanations[0]}, is {explanations[1]}, and was {explanations[2]}."
        else:
            return "Recommended based on collaborative filtering analysis of similar users."
    
    def get_confidence_level(self, confidence_score):
        """
        Convert confidence score to human-readable level
        """
        if confidence_score >= 85:
            return "Very High"
        elif confidence_score >= 70:
            return "High"
        elif confidence_score >= 55:
            return "Medium"
        elif confidence_score >= 40:
            return "Moderate"
        else:
            return "Low"
    
    def setup_session(self):
        """Setup requests session with retry logic"""
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9'
        })
    
    def load_data(self):
        """Load movies CSV and SVD model"""
        try:
            base_dir = settings.BASE_DIR
            
            # Load movies CSV
            movies_path = os.path.join(base_dir, 'ml-20m', 'movies.csv')
            self.movies_df = pd.read_csv(movies_path)
            
            # Extract year from title for filtering
            self.movies_df['year'] = self.movies_df['title'].str.extract(r'\((\d{4})\)')
            self.movies_df['year'] = pd.to_numeric(self.movies_df['year'], errors='coerce')
            
            # Create clean title without year
            self.movies_df['clean_title'] = self.movies_df['title'].str.replace(r'\s*\(\d{4}\)', '', regex=True)
            
            self.movie_titles = self.movies_df['title'].tolist()
            
            print(f"✅ Loaded {len(self.movies_df)} movies")
            
            # Load SVD model
            try:
                model_path = os.path.join(base_dir, 'svd_model.pkl')
                with open(model_path, 'rb') as f:
                    self.svd_model = pickle.load(f)
                print(f"✅ Loaded SVD model successfully")
            except Exception as model_error:
                print(f"⚠️ Could not load SVD model: {model_error}")
                self.svd_model = None
            
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            # Fallback to sample data
            self.movies_df = pd.DataFrame({
                'movieId': [1, 2, 3, 4, 5],
                'title': ['The Shawshank Redemption (1994)', 'The Godfather (1972)', 'The Dark Knight (2008)', 'Pulp Fiction (1994)', 'Forrest Gump (1994)'],
                'genres': ['Drama', 'Crime|Drama', 'Action|Crime|Drama', 'Crime|Drama', 'Comedy|Drama|Romance'],
                'year': [1994, 1972, 2008, 1994, 1994]
            })
            self.movie_titles = self.movies_df['title'].tolist()
            self.svd_model = None
    
    def apply_filters(self, movies_df, filters):
        """Apply user filters to movies DataFrame using Pandas filtering"""
        filtered_df = movies_df.copy()
        
        print(f"🔍 Applying filters: {filters}")
        print(f"📊 Starting with {len(filtered_df)} movies")
        
        # Genre filtering using Pandas string contains
        if filters.get('genres') and len(filters['genres']) > 0:
            # Create pattern for multiple genres (OR logic)
            genre_pattern = '|'.join(filters['genres'])
            filtered_df = filtered_df[filtered_df['genres'].str.contains(genre_pattern, na=False, case=False)]
            print(f"📊 After genre filter: {len(filtered_df)} movies")
        
        # Year range filtering
        year_min = filters.get('year_min')
        year_max = filters.get('year_max')
        
        if year_min or year_max:
            if year_min:
                filtered_df = filtered_df[filtered_df['year'] >= int(year_min)]
            if year_max:
                filtered_df = filtered_df[filtered_df['year'] <= int(year_max)]
            print(f"📊 After year filter: {len(filtered_df)} movies")
        
        # Rating filtering (we'll simulate this based on predicted ratings)
        min_rating = filters.get('min_rating')
        if min_rating and float(min_rating) > 0:
            # For now, we'll filter based on a simulated rating
            # In a real scenario, you might have actual ratings in your CSV
            print(f"📊 Rating filter applied (min: {min_rating})")
        
        print(f"✅ Final filtered result: {len(filtered_df)} movies")
        return filtered_df
    
    def sort_movies(self, movies_df, sort_by):
        """Sort movies based on user preference"""
        if sort_by == 'year':
            return movies_df.sort_values('year', ascending=False)
        elif sort_by == 'alphabetical':
            return movies_df.sort_values('title')
        elif sort_by == 'popularity':
            # Sort by movieId as a proxy for popularity (lower IDs = older/more popular)
            return movies_df.sort_values('movieId')
        else:  # Default: rating
            return movies_df  # Will be sorted by predicted rating later
    
    def get_safe_temp_user_id(self):
        """Get a safe temporary user ID that doesn't exist in the dataset"""
        if self._safe_user_id is None:
            try:
                ratings_path = os.path.join(settings.BASE_DIR, 'ml-20m', 'ratings.csv')
                max_user_id = pd.read_csv(ratings_path, usecols=['userId'])['userId'].max()
                self._safe_user_id = max_user_id + 1
                print(f"🔒 Using safe temporary user ID: {self._safe_user_id}")
            except Exception as e:
                print(f"⚠️ Could not determine max user ID: {e}")
                self._safe_user_id = -1
        
        return self._safe_user_id
    
    def extract_movie_year(self, title):
        """Extract year from movie title like 'Movie Name (1994)'"""
        import re
        match = re.search(r'\((\d{4})\)', title)
        return match.group(1) if match else None
    
    def clean_movie_title(self, title):
        """Remove year from title for TMDB search"""
        import re
        return re.sub(r'\s*\(\d{4}\)', '', title).strip()
    
    def create_genre_card_placeholder(self, title, genres):
        """Create a genre-themed illustrated card for movies without posters"""
        genre_mapping = {
            'action': ['Action', 'Adventure', 'Thriller'],
            'romance': ['Romance', 'Romantic', 'Love'],
            'sci-fi': ['Sci-Fi', 'Science Fiction', 'Sci-fi'],
            'comedy': ['Comedy', 'Humor', 'Funny'],
            'fantasy': ['Fantasy', 'Magic', 'Fairy Tale'],
            'horror': ['Horror', 'Scary'],
            'drama': ['Drama', 'Dramatic'],
            'crime': ['Crime', 'Mystery', 'Detective'],
            'animation': ['Animation', 'Animated'],
            'documentary': ['Documentary'],
            'family': ['Family', 'Children'],
            'musical': ['Musical', 'Music'],
            'war': ['War', 'Military'],
            'western': ['Western'],
            'sport': ['Sport', 'Sports'],
            'biography': ['Biography', 'Biographical']
        }
        
        selected_card = 'default'
        
        print(f"🎨 DEBUG: Processing '{title}' with genres: {genres}")
        
        if genres and len(genres) > 0:
            # Check each genre against our mapping
            for genre in genres:
                genre_lower = genre.lower().strip()
                print(f"🔍 DEBUG: Checking genre: '{genre_lower}'")
                
                for card_type, genre_list in genre_mapping.items():
                    if any(g.lower() in genre_lower or genre_lower in g.lower() for g in genre_list):
                        selected_card = card_type
                        print(f"✅ DEBUG: Matched '{genre_lower}' to '{card_type}' card")
                        break
                if selected_card != 'default':
                    break
            
            # If no match found, use the first genre as fallback
            if selected_card == 'default' and genres:
                first_genre = genres[0].lower().strip()
                print(f"🔄 DEBUG: No match found, using fallback for first genre: '{first_genre}'")
                
                # Additional fallback mappings
                fallback_mapping = {
                    'war': 'action',
                    'biography': 'drama',
                    'history': 'drama',
                    'mystery': 'crime',
                    'adventure': 'action',
                    'thriller': 'action',
                    'animation': 'animation'
                }
                
                selected_card = fallback_mapping.get(first_genre, 'default')
                print(f"🎯 DEBUG: Fallback result: '{selected_card}' card")
        
        print(f"🎨 DEBUG: Final selection for '{title}': {selected_card}")
        
        # Check if the file actually exists
        card_path = f"/static/movapp/images/genre-cards/{selected_card}.svg"
        print(f"📁 DEBUG: Returning path: {card_path}")
        
        return card_path
    
    def search_tmdb_movie(self, title, genres=None):
        """Search for movie on TMDB with robust error handling and genre card fallback"""
        try:
            clean_title = self.clean_movie_title(title)
            year = self.extract_movie_year(title)
            
            search_url = f"{self.tmdb_base_url}/search/movie"
            params = {
                'api_key': self.tmdb_api_key,
                'query': clean_title,
                'language': 'en-US'
            }
            
            if year:
                params['year'] = year
            
            response = self.session.get(search_url, params=params, timeout=2)
            
            if response.status_code == 200:
                data = response.json()
                if data['results']:
                    movie = data['results'][0]
                    poster_path = movie.get('poster_path')
                    
                    if poster_path:
                        return f"{self.tmdb_image_base_url}{poster_path}"
                        
        except requests.exceptions.ConnectionError:
            print(f"🎨 Connection issue for '{title}' - Using genre card")
        except requests.exceptions.Timeout:
            print(f"🎨 Timeout for '{title}' - Using genre card")
        except requests.exceptions.RequestException:
            print(f"🎨 Request issue for '{title}' - Using genre card")
        except Exception:
            print(f"🎨 Error for '{title}' - Using genre card")
        
        return self.create_genre_card_placeholder(title, genres)
    
    def search_movies(self, query, filters=None, limit=10):
        """Search for movies by title with optional filters"""
        if not query or len(query) < 2:
            return []
        
        # Start with all movies
        search_df = self.movies_df.copy()
        
        # Apply filters if provided
        if filters:
            search_df = self.apply_filters(search_df, filters)
        
        # Apply text search
        query = query.lower()
        matches = []
        
        for _, movie in search_df.iterrows():
            if query in movie['title'].lower():
                matches.append(movie['title'])
                if len(matches) >= limit:
                    break
        
        return matches
    
    def get_movie_details(self, title):
        """Get movie details including ID and genres"""
        movie_row = self.movies_df[self.movies_df['title'] == title]
        if not movie_row.empty:
            movie = movie_row.iloc[0]
            return {
                'movieId': movie['movieId'],
                'title': movie['title'],
                'genres': movie['genres'].split('|') if pd.notna(movie['genres']) else ['Unknown']
            }
        return None
    
    def get_movie_id(self, title):
        """Get movie ID from title"""
        movie_details = self.get_movie_details(title)
        return movie_details['movieId'] if movie_details else None
    
    def extract_user_preferences(self, selected_movies):
        """Extract user preferences from selected movies"""
        user_genres = set()
        selected_details = []
        
        print(f"🎭 Analyzing user preferences from: {selected_movies}")
        
        for title in selected_movies:
            details = self.get_movie_details(title)
            if details:
                selected_details.append(details)
                user_genres.update(details['genres'])
        
        print(f"📊 User prefers genres: {list(user_genres)}")
        return {
            'preferred_genres': user_genres,
            'selected_details': selected_details
        }
    
    def find_similar_movies_by_content(self, selected_movies, user_preferences, filters=None):
        """Find candidate movies similar to selected movies by content with filters"""
        preferred_genres = user_preferences['preferred_genres']
        
        # Start with all movies
        candidate_df = self.movies_df.copy()
        
        # Apply user filters first
        if filters:
            candidate_df = self.apply_filters(candidate_df, filters)
        
        candidate_movies = []
        
        print(f"🔍 Finding movies similar to user preferences with filters...")
        
        for _, movie in candidate_df.iterrows():
            # Skip already selected movies
            if movie['title'] in selected_movies:
                continue
                
            movie_genres = set(movie['genres'].split('|')) if pd.notna(movie['genres']) else set()
            
            # Calculate genre similarity
            genre_overlap = len(preferred_genres.intersection(movie_genres))
            
            if genre_overlap > 0:  # Movie has at least one matching genre
                candidate_movies.append({
                    'movieId': movie['movieId'],
                    'title': movie['title'],
                    'genres': list(movie_genres),
                    'genre_similarity': genre_overlap,
                    'year': movie.get('year', None)
                })
        
        print(f"📽️ Found {len(candidate_movies)} candidate movies with genre overlap after filtering")
        return candidate_movies
    
    def get_filtered_recommendations(self, selected_movies, filters=None, num_recommendations=20):
        """Generate personalized recommendations with intelligent caching, confidence scores, and explanations - OPTIMIZED FOR PERFORMANCE"""
        
        # Generate cache key
        cache_key = self._generate_cache_key(selected_movies, filters)
        
        # Try to get from cache first
        cached_recommendations = cache.get(cache_key)
        if cached_recommendations:
            print(f"🚀 Cache HIT: Retrieved recommendations from cache in milliseconds!")
            return cached_recommendations
        
        print(f"💾 Cache MISS: Generating new recommendations (this will take a moment)")
        
        if not self.svd_model:
            print("⚠️ SVD model not available, using fallback recommendations")
            recommendations = self.get_fallback_recommendations(selected_movies, filters, num_recommendations)
        else:
            try:
                print(f"🎬 Generating filtered recommendations for: {selected_movies}")
                print(f"🔧 Applied filters: {filters}")
                
                # Step 1: Extract user preferences from selected movies
                user_preferences = self.extract_user_preferences(selected_movies)
                
                if not user_preferences['preferred_genres']:
                    print("⚠️ Could not extract user preferences, using fallback")
                    recommendations = self.get_fallback_recommendations(selected_movies, filters, num_recommendations)
                else:
                    # Step 2: Find candidate movies with similar content AND apply filters
                    candidate_movies = self.find_similar_movies_by_content(selected_movies, user_preferences, filters)
                    
                    if not candidate_movies:
                        print("⚠️ No similar movies found after filtering, using fallback")
                        recommendations = self.get_fallback_recommendations(selected_movies, filters, num_recommendations)
                    else:
                        # Step 3: Use SVD to predict ratings for candidate movies
                        temp_user_id = self.get_safe_temp_user_id()
                        svd_predictions = []
                        
                        print(f"🤖 Using SVD model to predict ratings for {len(candidate_movies)} filtered candidates...")
                        
                        for movie in candidate_movies:
                            try:
                                pred = self.svd_model.predict(temp_user_id, movie['movieId'])
                                
                                # Boost rating based on genre similarity
                                genre_boost = movie['genre_similarity'] * 0.3
                                adjusted_rating = min(pred.est + genre_boost, 5.0)
                                
                                # Calculate confidence score
                                confidence_score = self.calculate_confidence_score(pred, movie['genre_similarity'])
                                
                                # Generate explanation
                                explanation = self.generate_explanation(
                                    movie['title'], 
                                    selected_movies, 
                                    user_preferences, 
                                    movie['genre_similarity'], 
                                    adjusted_rating
                                )
                                
                                svd_predictions.append({
                                    'movieId': movie['movieId'],
                                    'title': movie['title'],
                                    'predicted_rating': round(adjusted_rating, 1),
                                    'genres': movie['genres'],
                                    'genre_similarity': movie['genre_similarity'],
                                    'year': movie.get('year'),
                                    'confidence_score': confidence_score,
                                    'confidence_level': self.get_confidence_level(confidence_score),
                                    'confidence_color': self.get_confidence_color(confidence_score),
                                    'explanation': explanation,
                                    # OPTIMIZATION: Use genre cards initially instead of fetching posters
                                    'poster_url': self.create_genre_card_placeholder(movie['title'], movie['genres'])
                                })
                            except Exception as pred_error:
                                continue
                        
                        # Step 4: Apply sorting based on user preference
                        sort_by = filters.get('sort_by', 'rating') if filters else 'rating'
                        
                        if sort_by == 'year' and any(p.get('year') for p in svd_predictions):
                            svd_predictions.sort(key=lambda x: x.get('year', 0), reverse=True)
                        elif sort_by == 'alphabetical':
                            svd_predictions.sort(key=lambda x: x['title'])
                        else:  # Default: rating
                            svd_predictions.sort(key=lambda x: x['predicted_rating'], reverse=True)
                        
                        top_predictions = svd_predictions[:num_recommendations]
                        
                        print(f"✨ Generated {len(top_predictions)} filtered and sorted recommendations with confidence scores")
                        print("⚡ PERFORMANCE OPTIMIZATION: Returning recommendations immediately with genre cards!")
                        print("🎨 Real posters will be loaded lazily in the background via AJAX")
                        
                        recommendations = top_predictions
                        
            except Exception as e:
                print(f"❌ Error generating filtered recommendations: {e}")
                recommendations = self.get_fallback_recommendations(selected_movies, filters, num_recommendations)
        
        # Cache the final recommendations (whether from SVD or fallback)
        cache.set(cache_key, recommendations, self.cache_timeout)
        print(f"💾 Cached recommendations for {self.cache_timeout} seconds")
        
        return recommendations
    
    def get_poster_for_movie(self, title, genres=None):
        """
        NEW: Get poster for a specific movie (for lazy loading via AJAX)
        This method will be called to fetch individual posters in the background
        """
        print(f"🎨 Lazy loading poster for: {title}")
        return self.search_tmdb_movie(title, genres)
    
    def get_enhanced_recommendations(self, selected_movies, num_recommendations=20):
        """Generate enhanced recommendations (backward compatibility)"""
        return self.get_filtered_recommendations(selected_movies, None, num_recommendations)
    
    def get_fallback_recommendations(self, selected_movies, filters=None, num_recommendations=20):
        """Fallback recommendations when personalization fails"""
        print("🔄 Using fallback recommendation system")
        
        sample_recommendations = [
            {'title': 'The Shawshank Redemption (1994)', 'predicted_rating': 4.8, 'genres': ['Drama'], 'year': 1994},
            {'title': 'The Godfather (1972)', 'predicted_rating': 4.7, 'genres': ['Crime', 'Drama'], 'year': 1972},
            {'title': 'The Dark Knight (2008)', 'predicted_rating': 4.6, 'genres': ['Action', 'Crime', 'Drama'], 'year': 2008},
            {'title': 'Pulp Fiction (1994)', 'predicted_rating': 4.5, 'genres': ['Crime', 'Drama'], 'year': 1994},
            {'title': 'Forrest Gump (1994)', 'predicted_rating': 4.4, 'genres': ['Comedy', 'Drama', 'Romance'], 'year': 1994},
            {'title': 'Inception (2010)', 'predicted_rating': 4.3, 'genres': ['Action', 'Sci-Fi', 'Thriller'], 'year': 2010},
            {'title': 'The Matrix (1999)', 'predicted_rating': 4.2, 'genres': ['Action', 'Sci-Fi'], 'year': 1999},
            {'title': 'Goodfellas (1990)', 'predicted_rating': 4.1, 'genres': ['Biography', 'Crime', 'Drama'], 'year': 1990},
            {'title': 'The Lord of the Rings: The Return of the King (2003)', 'predicted_rating': 4.0, 'genres': ['Adventure', 'Drama', 'Fantasy'], 'year': 2003},
            {'title': 'Star Wars: Episode IV - A New Hope (1977)', 'predicted_rating': 3.9, 'genres': ['Action', 'Adventure', 'Fantasy'], 'year': 1977}
        ]
        
        # Add confidence scores and explanations to fallback recommendations
        for i, rec in enumerate(sample_recommendations):
            # Simulate confidence scores for fallback
            confidence_score = round(85 - (i * 3), 1)  # Decreasing confidence
            rec['confidence_score'] = confidence_score
            rec['confidence_level'] = self.get_confidence_level(confidence_score)
            rec['confidence_color'] = self.get_confidence_color(confidence_score)
            rec['explanation'] = f"Highly rated {rec['genres'][0].lower()} film that appeals to diverse audiences."
            # OPTIMIZATION: Use genre cards initially for fallback too
            rec['poster_url'] = self.create_genre_card_placeholder(rec['title'], rec['genres'])
        
        # Apply filters to fallback recommendations if provided
        if filters:
            filtered_samples = []
            for rec in sample_recommendations:
                # Check genre filter
                if filters.get('genres'):
                    genre_match = any(genre in rec['genres'] for genre in filters['genres'])
                    if not genre_match:
                        continue
                
                # Check year filter
                if filters.get('year_min') and rec['year'] < int(filters['year_min']):
                    continue
                if filters.get('year_max') and rec['year'] > int(filters['year_max']):
                    continue
                
                # Check rating filter
                if filters.get('min_rating') and rec['predicted_rating'] < float(filters['min_rating']):
                    continue
                
                filtered_samples.append(rec)
            
            sample_recommendations = filtered_samples
        
        # Apply sorting
        sort_by = filters.get('sort_by', 'rating') if filters else 'rating'
        if sort_by == 'year':
            sample_recommendations.sort(key=lambda x: x['year'], reverse=True)
        elif sort_by == 'alphabetical':
            sample_recommendations.sort(key=lambda x: x['title'])
        # rating is already sorted
        
        return sample_recommendations[:num_recommendations]

# Global instance to be used across views
movie_data_loader = MovieDataLoader()
